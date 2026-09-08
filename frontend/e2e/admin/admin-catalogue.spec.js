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
 * The product form: create, edit, deactivate (US-A2).
 *
 * The assertion this spec exists for is the one that is easiest to get wrong
 * and hardest to see in a screenshot: **a validation error lands on its own
 * field, not in one banner at the top**. US-A2 asks for exactly that, and the
 * API's envelope already names the field (`{"error": {"field": "sku", ...}}`),
 * so what is really being tested is whether the form honours it.
 *
 * "On its own field" is checked structurally rather than by eye: the input's
 * `aria-describedby` must point at the element holding the message. That is
 * also the property that makes the message reach a screen reader, so the two
 * are the same test.
 *
 * Both halves are exercised: a rule the browser can enforce (a blank name)
 * and a rule only the database knows (an SKU already in use). The second is
 * the one that proves the envelope is wired up at all.
 */

const UNIQUE = Date.now().toString(36)

/**
 * The message the input itself points at, or '' if it points at nothing.
 *
 * This is what "next to its field" means in a way a machine can check: the
 * control's `aria-describedby` resolves to the element carrying the message.
 * A form that rendered the same text in a banner at the top would leave this
 * empty, and it is the same wiring that makes the message reach a screen
 * reader (PRD §9.3).
 *
 * The id is matched as an attribute rather than with `#id` on purpose --
 * React's useId produces `:r7:`, which is not a legal CSS id selector.
 */
async function fieldError(page, label) {
  const describedBy = await page
    .getByLabel(labelled(label))
    .getAttribute('aria-describedby')
  if (!describedBy) return ''
  for (const id of describedBy.split(/\s+/).filter(Boolean)) {
    const node = page.locator(`[id="${id}"][role="alert"]`)
    if ((await node.count()) > 0) return (await node.innerText()).trim()
  }
  return ''
}

test('a per-field validation error renders against its own field, twice over', async ({
  page,
  baseURL,
}) => {
  // The SKU collision below is provoked on purpose, so the 422 it earns is
  // named here rather than left to look like an accident.
  const problems = watchConsole(page, {
    allow: [{ url: /\/api\/v1\/admin\/products\/$/, status: 422 }],
  })
  const admin = tokensFor(SEEDED_ADMIN.email)
  // An existing SKU to collide with. The fixture mints its own, so this test
  // never depends on a particular row in the demo catalogue.
  const existing = fixture('product', ['--stock', '4'])

  await useSession(page, baseURL, admin)
  await page.goto('/admin/products/new')
  await expect(page.getByRole('heading', { name: 'New product', level: 1 })).toBeVisible()

  // --- what the browser can refuse on its own -----------------------------
  await page.getByRole('button', { name: 'Create product' }).click()

  await expect(page.getByLabel(labelled('Name'))).toHaveAttribute(
    'aria-invalid',
    'true',
  )
  expect(await fieldError(page, 'Name')).toBe('Name is required.')
  expect(await fieldError(page, 'Category')).toBe('Choose a category.')
  expect(await fieldError(page, 'SKU')).toBe('SKU is required.')
  expect(await fieldError(page, 'Price (৳)')).toBe('Enter an amount like 62500.00')

  // Each message appears exactly once on the page. A form that also mirrored
  // them into a banner would double every one of these.
  await expect(page.getByText('Name is required.')).toHaveCount(1)

  // --- what only the database can refuse ----------------------------------
  await page.getByLabel(labelled('Name')).fill(`E2E Form Product ${UNIQUE}`)
  await page
    .getByLabel(labelled('Category'))
    .selectOption({ label: 'E2E Fixtures' })
  await page.getByLabel(labelled('SKU')).fill(existing.sku)
  await page.getByLabel(labelled('Price (৳)')).fill('3199.00')
  await page.getByLabel(labelled('Opening stock')).fill('12')

  await page.getByRole('button', { name: 'Create product' }).click()

  // SKU_TAKEN, field "sku" -- routed onto the variant's own SKU input rather
  // than dumped at the top of the form.
  await expect
    .poll(() => fieldError(page, 'SKU'), { timeout: 15_000 })
    .toContain(existing.sku)
  expect(await fieldError(page, 'SKU')).toMatch(/already in use/i)
  // Still on the form: a refused create must not navigate anywhere.
  await expect(page).toHaveURL(/\/admin\/products\/new$/)

  expect(problems, problems.join('\n')).toEqual([])
})

test('create, edit, then deactivate a product through the form', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)

  const name = `E2E Lifecycle ${UNIQUE}`
  const renamed = `${name} (revised)`
  const sku = `E2E-LIFE-${UNIQUE.toUpperCase()}`

  await useSession(page, baseURL, admin)
  await page.goto('/admin/products/new')

  await page.getByLabel(labelled('Name')).fill(name)
  await page
    .getByLabel(labelled('Category'))
    .selectOption({ label: 'E2E Fixtures' })
  await page.getByLabel(labelled('Description')).fill('Created by the e2e suite.')
  await page.getByLabel(labelled('Specification 1 label')).fill('Made by')
  await page.getByLabel(labelled('Specification 1 value')).fill('Playwright')
  await page.getByLabel(labelled('SKU')).fill(sku)
  await page.getByLabel(labelled('Option label')).fill('Standard')
  await page.getByLabel(labelled('Price (৳)')).fill('3199.00')
  await page.getByLabel(labelled('Opening stock')).fill('12')

  await page.getByRole('button', { name: 'Create product' }).click()

  // --- created ------------------------------------------------------------
  await expect(page).toHaveURL(/\/admin\/products\/\d+$/)
  await expect(page.getByText('Product created.', { exact: false })).toBeVisible()
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible()

  const productId = Number(page.url().split('/').pop())
  const created = await (
    await request.get(`/api/v1/admin/products/${productId}/`, {
      headers: bearer(admin.access),
    })
  ).json()
  expect(created.name).toBe(name)
  expect(created.is_active).toBe(true)
  expect(created.variants).toHaveLength(1)
  expect(created.variants[0]).toMatchObject({ sku, price: '3199.00', stock: 12 })
  // The opening quantity went through the ledger, not into the column: a
  // variant reconciles from its first second (docs/api-contract-admin-catalogue.md).
  const ledger = await (
    await request.get(`/api/v1/admin/inventory/${created.variants[0].id}/logs/`, {
      headers: bearer(admin.access),
    })
  ).json()
  expect(ledger.logged_stock).toBe(12)
  expect(ledger.logs[0]).toMatchObject({ delta: 12, reason: 'initial' })

  // --- edited -------------------------------------------------------------
  await page.getByLabel(labelled('Name')).fill(renamed)
  await page.getByRole('button', { name: 'Save changes' }).click()
  await expect(page.getByText('Saved.', { exact: true })).toBeVisible()

  const edited = await (
    await request.get(`/api/v1/admin/products/${productId}/`, {
      headers: bearer(admin.access),
    })
  ).json()
  expect(edited.name).toBe(renamed)
  // The edit is a PATCH of the product's own fields; the variant is untouched,
  // because folding variants into a product save is how a partial write
  // quietly deletes one an order line still points at.
  expect(edited.variants[0].sku).toBe(sku)

  // --- deactivated --------------------------------------------------------
  await page.goto('/admin/products')
  await page.getByLabel(labelled('Search')).fill(renamed)

  const row = page.getByRole('row').filter({ hasText: renamed })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText('Active')
  await row.getByRole('button', { name: 'Deactivate' }).click()
  await expect(row).toContainText('Inactive')
  await expect(row.getByRole('button', { name: 'Activate' })).toBeVisible()

  const withdrawn = await (
    await request.get(`/api/v1/admin/products/${productId}/`, {
      headers: bearer(admin.access),
    })
  ).json()
  // DELETE deactivates; nothing is destroyed, so the row is still readable and
  // the SKU an order might have snapshotted still exists.
  expect(withdrawn.is_active).toBe(false)
  expect(withdrawn.variants[0].sku).toBe(sku)

  // And it is gone from the storefront, which is the point of deactivating it.
  const storefront = await request.get(`/api/v1/products/${withdrawn.slug}/`)
  expect(storefront.status()).toBe(404)

  expect(problems, problems.join('\n')).toEqual([])
})
