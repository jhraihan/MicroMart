import { expect, test } from '@playwright/test'

import {
  SEEDED_ADMIN,
  bearer,
  fixture,
  labelled,
  tokensFor,
  useSession,
  watchConsole,
} from './_support.js'

/*
 * Stock adjustment and the ledger behind it (US-A4, FR-INV-8, PRD §6.4).
 *
 * The invariant on trial: **stock never moves without a reason, and every
 * movement leaves a row**. Summing those rows must equal the number on the
 * variant, which is the whole justification for stock not being an editable
 * field anywhere else — so the adjustment dialog is checked for the refusal
 * when the reason is missing, for the ledger row when it is not, and the
 * screen's reconciliation claim is checked against the server's own sum.
 *
 * The last test closes the back door: if `PATCH /admin/variants/{id}/` would
 * accept a `stock` key, none of the above would be worth anything.
 */

const OPENING = 10
const DELTA = 7

/** The message the control itself points at — see admin-catalogue.spec.js. */
async function fieldError(scope, page, label) {
  const describedBy = await scope
    .getByLabel(labelled(label))
    .getAttribute('aria-describedby')
  if (!describedBy) return ''
  for (const id of describedBy.split(/\s+/).filter(Boolean)) {
    const node = page.locator(`[id="${id}"][role="alert"]`)
    if ((await node.count()) > 0) return (await node.innerText()).trim()
  }
  return ''
}

async function ledgerFor(request, access, variantId) {
  const response = await request.get(`/api/v1/admin/inventory/${variantId}/logs/`, {
    headers: bearer(access),
  })
  expect(response.status(), await response.text()).toBe(200)
  return response.json()
}

test('an adjustment needs a reason, and the reason it gets ends up in the ledger', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)
  const product = fixture('product', ['--stock', String(OPENING)])

  await useSession(page, baseURL, admin)
  // The search term lives in the URL so a variant editor can link straight to
  // an SKU; that is also the shortest way in for a test.
  await page.goto(`/admin/inventory?q=${encodeURIComponent(product.sku)}`)
  await expect(page.getByRole('heading', { name: 'Inventory', level: 1 })).toBeVisible()

  const row = page.getByRole('row').filter({ hasText: product.sku })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText(String(OPENING))
  await row.getByRole('button', { name: 'Adjust' }).click()

  const dialog = page.getByRole('dialog', { name: `Adjust stock — ${product.sku}` })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText(`Current stock: ${OPENING}`)

  // --- no reason, no movement --------------------------------------------
  await dialog.getByLabel(labelled('Change in units')).fill(String(DELTA))
  // The dialog previews the result before anything is written, which is the
  // difference between "record 7" and "set it to 7".
  await expect(dialog).toContainText(`after this adjustment: ${OPENING + DELTA}`)

  await dialog.getByRole('button', { name: 'Record adjustment' }).click()
  expect(await fieldError(dialog, page, 'Reason')).toBe('Choose why the stock is moving.')

  const untouched = await ledgerFor(request, admin.access, product.variant_id)
  expect(untouched.stock).toBe(OPENING)
  expect(untouched.logs).toHaveLength(1) // the opening `initial` row, nothing else

  // --- with a reason ------------------------------------------------------
  await dialog.getByLabel(labelled('Reason')).selectOption('restock')
  await dialog.getByLabel(labelled('Note')).fill('Carton from the distributor')
  await dialog.getByRole('button', { name: 'Record adjustment' }).click()

  await expect(dialog).toContainText(
    `Recorded +${DELTA} for Restock. Stock is now ${OPENING + DELTA}.`,
  )

  // --- the movement history, on screen ------------------------------------
  const history = dialog
    .getByRole('table', { name: /Every recorded movement for this variant/i })
    .getByRole('row')
    .filter({ hasText: 'Carton from the distributor' })
  await expect(history).toHaveCount(1)
  await expect(history).toContainText(`+${DELTA}`)
  await expect(history).toContainText('Restock')
  // Who moved it. A ledger nobody can be identified from explains nothing.
  await expect(history).toContainText(SEEDED_ADMIN.email)

  // The screen prints the ledger's own sum beside the column precisely so a
  // drift between the two is visible rather than theoretical.
  await expect(dialog.getByText('Reconciled')).toBeVisible()

  // --- and the server -----------------------------------------------------
  const ledger = await ledgerFor(request, admin.access, product.variant_id)
  expect(ledger.stock).toBe(OPENING + DELTA)
  expect(ledger.logged_stock).toBe(ledger.stock)
  expect(ledger.logs[0]).toMatchObject({
    delta: DELTA,
    reason: 'restock',
    note: 'Carton from the distributor',
    actor_email: SEEDED_ADMIN.email,
  })
  expect(ledger.logs.map((log) => log.delta).reduce((a, b) => a + b, 0)).toBe(ledger.stock)

  expect(problems, problems.join('\n')).toEqual([])
})

test('the ledger refuses a reason only the order state machine may write', async ({
  request,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  const product = fixture('product', ['--stock', '5'])

  // `order_confirmed` is written by the state machine when it moves stock. A
  // hand-typed one would put a movement in the ledger that no order accounts
  // for, so the choice list excludes it.
  const response = await request.post('/api/v1/admin/inventory/adjust/', {
    headers: bearer(admin.access),
    data: {
      variant_id: product.variant_id,
      delta: 3,
      reason: 'order_confirmed',
      note: 'should not be possible',
    },
  })
  expect(response.status()).toBe(400)

  const ledger = await ledgerFor(request, admin.access, product.variant_id)
  expect(ledger.stock).toBe(5)
  expect(ledger.logged_stock).toBe(5)
})

test('stock is not a writable field on a variant', async ({ request }) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  const product = fixture('product', ['--stock', '5'])

  const response = await request.patch(
    `/api/v1/admin/variants/${product.variant_id}/`,
    { headers: bearer(admin.access), data: { stock: 500 } },
  )
  // Refused, not ignored. Silently dropping the key would let a caller
  // believe stock had moved while the ledger said otherwise.
  expect(response.status()).toBe(422)
  expect((await response.json()).error).toMatchObject({ code: 'STOCK_NOT_WRITABLE' })

  const ledger = await ledgerFor(request, admin.access, product.variant_id)
  expect(ledger.stock).toBe(5)
  expect(ledger.logged_stock).toBe(5)
})

test('the low-stock filter is the reorder list, and a variant joins it by falling', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)
  // Threshold is 5; opening at 9 keeps it off the list until stock is moved.
  const product = fixture('product', ['--stock', '9'])

  const dropped = await request.post('/api/v1/admin/inventory/adjust/', {
    headers: bearer(admin.access),
    data: {
      variant_id: product.variant_id,
      delta: -5,
      reason: 'damage',
      note: 'Water damage in transit',
    },
  })
  expect(dropped.status(), await dropped.text()).toBe(200)

  await useSession(page, baseURL, admin)
  await page.goto(`/admin/inventory?q=${encodeURIComponent(product.sku)}&low_stock=true`)

  const row = page.getByRole('row').filter({ hasText: product.sku })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Low')

  const ledger = await ledgerFor(request, admin.access, product.variant_id)
  expect(ledger.stock).toBe(4)
  expect(ledger.logged_stock).toBe(4)
  expect(ledger.logs[0]).toMatchObject({ delta: -5, reason: 'damage' })

  expect(problems, problems.join('\n')).toEqual([])
})
