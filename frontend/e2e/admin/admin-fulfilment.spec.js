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
 * The fulfilment loop (US-A3, FR-ADM-5, FR-ORD-7) and the state machine that
 * guards it (PRD §15.1).
 *
 * PRD §3.2 asks that the owner be able to see an order, confirm it, pack it
 * and ship it in under a minute. That is a real requirement with a real
 * number in it, so the walk is timed from arriving at the pipeline to the
 * order reading `delivered`, and the budget is asserted.
 *
 * Both halves of the state machine are proved, because only one of them is
 * the control:
 *
 * * the screen offers exactly the moves the server would accept, and
 * * the server refuses a move the screen never offered, with 422, **and does
 *   not log it** -- an append-only audit trail that records refusals is not an
 *   audit trail of what happened.
 *
 * The final word on every assertion is the API, not the DOM. A green badge is
 * a report of the truth; `GET /admin/orders/{ref}/` is the truth.
 */

const FULFILMENT_BUDGET_MS = 60_000

/** Every forward move the pipeline offers, in the order the pipeline runs. */
const FORWARD_LABELS = {
  confirmed: 'Confirm order',
  packed: 'Mark packed',
  shipped: 'Mark shipped',
  delivered: 'Mark delivered',
}

async function adminOrder(request, access, reference) {
  const response = await request.get(`/api/v1/admin/orders/${reference}/`, {
    headers: bearer(access),
  })
  expect(response.status(), await response.text()).toBe(200)
  return response.json()
}

test('an admin walks a pending order to delivered in under a minute, and the log records every step', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)

  // An online order is left pending at placement -- stock untouched, nothing
  // agreed yet -- which is exactly the row that lands on the owner's desk.
  const order = fixture('order', ['--payment', 'online'])
  expect(order.status).toBe('pending')

  await useSession(page, baseURL, admin)

  // --- the clock starts where the owner's morning does: the pipeline -------
  const started = Date.now()
  await page.goto('/admin/orders')
  await expect(page.getByRole('heading', { name: 'Orders', level: 1 })).toBeVisible()

  // One search box for reference, name, email and phone, because the person
  // on the phone does not know which of them the system considers the key.
  await page.getByLabel(labelled('Search')).fill(order.reference)
  const row = page.getByRole('link', { name: order.reference })
  await expect(row).toBeVisible()
  await row.click()

  await expect(page.getByRole('heading', { name: order.reference })).toBeVisible()

  // --- pending: only the two moves the state machine allows ---------------
  await expect(page.getByRole('button', { name: FORWARD_LABELS.confirmed })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Cancel order' })).toBeVisible()
  for (const status of ['packed', 'shipped', 'delivered']) {
    await expect(page.getByRole('button', { name: FORWARD_LABELS[status] })).toHaveCount(0)
  }
  await expect(page.getByRole('button', { name: 'Record refund' })).toHaveCount(0)

  // --- confirm, pack ------------------------------------------------------
  await page.getByRole('button', { name: FORWARD_LABELS.confirmed }).click()
  await expect(page.getByRole('button', { name: FORWARD_LABELS.packed })).toBeVisible()

  await page.getByRole('button', { name: FORWARD_LABELS.packed }).click()
  await expect(page.getByRole('button', { name: FORWARD_LABELS.shipped })).toBeVisible()

  // --- ship: the courier record is the prerequisite, not a hidden field ----
  await page.getByRole('button', { name: FORWARD_LABELS.shipped }).click()

  const shipDialog = page.getByRole('dialog', { name: 'Ship this order' })
  await expect(shipDialog).toBeVisible()
  await expect(shipDialog).toContainText(
    'An order cannot be marked shipped without a courier and a tracking number.',
  )
  await shipDialog.getByLabel(labelled('Courier')).fill('Sundarban Courier')
  await shipDialog.getByLabel(labelled('Tracking number')).fill('SC-778899')
  await shipDialog.getByRole('button', { name: 'Save and mark shipped' }).click()

  await expect(page.getByRole('button', { name: FORWARD_LABELS.delivered })).toBeVisible()
  // Two writes, one gesture -- and the courier is now on the order.
  await expect(page.getByText('Sundarban Courier')).toBeVisible()
  await expect(page.getByText('SC-778899')).toBeVisible()

  // --- deliver ------------------------------------------------------------
  await page.getByRole('button', { name: FORWARD_LABELS.delivered }).click()
  // Delivered is not quite terminal: a refund is still recordable, and
  // nothing else is.
  await expect(page.getByRole('button', { name: 'Record refund' })).toBeVisible()
  for (const status of ['confirmed', 'packed', 'shipped', 'delivered']) {
    await expect(page.getByRole('button', { name: FORWARD_LABELS[status] })).toHaveCount(0)
  }

  const elapsed = Date.now() - started
  expect(
    elapsed,
    `PRD §3.2 budgets under a minute for this loop; it took ${Math.round(elapsed / 1000)}s`,
  ).toBeLessThan(FULFILMENT_BUDGET_MS)

  // --- the timeline on screen --------------------------------------------
  const timeline = page
    .locator('section')
    .filter({ has: page.getByRole('heading', { name: 'Status history' }) })
    .locator('ol > li')
  await expect(timeline).toHaveCount(5)
  await expect(timeline.nth(0)).toContainText('Order placed')
  await expect(timeline.nth(1)).toContainText('Pending → Confirmed')
  await expect(timeline.nth(2)).toContainText('Confirmed → Packed')
  await expect(timeline.nth(3)).toContainText('Packed → Shipped')
  await expect(timeline.nth(4)).toContainText('Shipped → Delivered')
  // An audit trail nobody can be identified from is not an audit trail, so
  // the admin who made the moves is named against them.
  await expect(timeline.nth(4)).toContainText(SEEDED_ADMIN.email)

  // --- and the server, which is the part that actually matters ------------
  const truth = await adminOrder(request, admin.access, order.reference)
  expect(truth.status).toBe('delivered')
  expect(truth.shipment.courier_name).toBe('Sundarban Courier')
  expect(truth.shipment.tracking_number).toBe('SC-778899')
  expect(truth.shipment.shipped_at).not.toBeNull()
  expect(truth.shipment.delivered_at).not.toBeNull()

  expect(truth.timeline.map((entry) => [entry.from_status, entry.to_status])).toEqual([
    ['', 'pending'],
    ['pending', 'confirmed'],
    ['confirmed', 'packed'],
    ['packed', 'shipped'],
    ['shipped', 'delivered'],
  ])
  for (const entry of truth.timeline.slice(1)) {
    expect(entry.actor_role).toBe('admin')
    expect(entry.actor_email).toBe(SEEDED_ADMIN.email)
  }
  // A delivered order can only be refunded from here (PRD §15.1's table, which
  // is authoritative over the diagram above it -- see docs/HANDOFF.md §4).
  expect(truth.allowed_transitions).toEqual(['refunded'])

  expect(problems, problems.join('\n')).toEqual([])
})

test('confirming an order decrements stock, and the ledger says why', async ({
  request,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  const order = fixture('order', ['--payment', 'online', '--stock', '9', '--quantity', '2'])

  const before = await (
    await request.get(`/api/v1/admin/inventory/${order.variant_id}/logs/`, {
      headers: bearer(admin.access),
    })
  ).json()
  expect(before.stock).toBe(9)

  const moved = await request.post(
    `/api/v1/admin/orders/${order.reference}/status/`,
    { headers: bearer(admin.access), data: { status: 'confirmed' } },
  )
  expect(moved.status(), await moved.text()).toBe(200)

  const after = await (
    await request.get(`/api/v1/admin/inventory/${order.variant_id}/logs/`, {
      headers: bearer(admin.access),
    })
  ).json()

  // Stock moves on confirmation and never on add-to-cart, and every movement
  // owes a ledger row that reconciles (PRD §6.4).
  expect(after.stock).toBe(7)
  expect(after.logged_stock).toBe(after.stock)
  expect(after.logs[0]).toMatchObject({
    delta: -2,
    reason: 'order_confirmed',
    order_reference: order.reference,
  })
})

test('an illegal transition is not offered, and is refused with 422 when forced', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)
  const order = fixture('order', ['--payment', 'online'])

  // --- the screen: the buttons are exactly the server's allowed_transitions
  await useSession(page, baseURL, admin)
  await page.goto(`/admin/orders/${order.reference}`)
  await expect(page.getByRole('heading', { name: order.reference })).toBeVisible()

  for (const label of ['Mark packed', 'Mark shipped', 'Mark delivered', 'Record refund']) {
    await expect(page.getByRole('button', { name: label })).toHaveCount(0)
  }

  // --- the server: the gate, which does not care what the screen drew ------
  const before = await adminOrder(request, admin.access, order.reference)
  expect(before.status).toBe('pending')
  expect(before.allowed_transitions.sort()).toEqual(['cancelled', 'confirmed'])

  const forced = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(admin.access),
    data: { status: 'delivered' },
  })
  expect(forced.status()).toBe(422)
  expect((await forced.json()).error).toMatchObject({
    code: 'ILLEGAL_STATUS_TRANSITION',
    field: 'status',
  })

  const after = await adminOrder(request, admin.access, order.reference)
  expect(after.status).toBe('pending')
  // A refused transition is not a state change, so it must leave no trace in
  // an append-only log whose whole purpose is to say what did happen.
  expect(after.timeline).toHaveLength(before.timeline.length)

  expect(problems, problems.join('\n')).toEqual([])
})

test('packed → shipped without a courier is refused, and the order stays packed', async ({
  request,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  // Walked to packed by the fixture, one legal step at a time, with no
  // shipment recorded -- which is the state the prerequisite exists for.
  const order = fixture('order', ['--payment', 'cod', '--advance-to', 'packed'])
  expect(order.status).toBe('packed')

  const forced = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(admin.access),
    data: { status: 'shipped' },
  })
  expect(forced.status()).toBe(422)
  expect((await forced.json()).error).toMatchObject({ code: 'SHIPMENT_REQUIRED' })

  const truth = await adminOrder(request, admin.access, order.reference)
  expect(truth.status).toBe('packed')
  expect(truth.shipment).toBeNull()

  // The record makes the move legal; nothing else about the request changed.
  const recorded = await request.post(
    `/api/v1/admin/orders/${order.reference}/shipment/`,
    {
      headers: bearer(admin.access),
      data: { courier_name: 'RedX', tracking_number: 'RX-4242' },
    },
  )
  expect(recorded.status(), await recorded.text()).toBe(200)

  const shipped = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(admin.access),
    data: { status: 'shipped' },
  })
  expect(shipped.status(), await shipped.text()).toBe(200)
  expect((await shipped.json()).status).toBe('shipped')
})

test('an unknown status is a 400 field error, not a state-machine answer', async ({
  request,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  const order = fixture('order', ['--payment', 'online'])

  const response = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(admin.access),
    data: { status: 'teleported' },
  })
  // The serializer validates the *vocabulary*; the state machine validates the
  // *move*. Conflating them would report a typo as an illegal transition.
  expect(response.status()).toBe(400)

  const truth = await adminOrder(request, admin.access, order.reference)
  expect(truth.status).toBe('pending')
})
