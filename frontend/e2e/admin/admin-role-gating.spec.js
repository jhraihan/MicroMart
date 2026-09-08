import { expect, test } from '@playwright/test'

import {
  ADMIN_ONLY_ENDPOINTS,
  ADMIN_ONLY_WRITES,
  SEEDED_ADMIN,
  SEEDED_CUSTOMER,
  bearer,
  fixture,
  signInWithForm,
  tokensFor,
  useSession,
  watchConsole,
} from './_support.js'

/*
 * Role gating, audited from outside the app (PRD §4.3 US-A8, §10.2, FR-ADM-10).
 *
 * The staff/admin split is one sentence: **staff may view orders and move
 * their status; everything else on the admin surface is the owner's.** It is
 * implemented per view rather than per prefix — `IsAdminOrStaff` on the whole
 * of `/api/v1/admin/` would have been shorter and wrong — so it is worth
 * auditing view by view rather than trusting the prefix.
 *
 * The API is where that is checked, because the API is the control. React
 * hiding a nav entry is a courtesy: it saves a staff member six links that
 * all dead-end in a refusal, and it is worth having, but a pasted URL, a
 * bookmark or curl goes straight past it. So the matrix below is asserted
 * against the endpoints, the writes as well as the reads, and only then is the
 * screen checked for the courtesy half.
 *
 * Two accounts sign in through the real form here — the staff one and the
 * customer one — because "this account can authenticate but may not do X" is
 * a different claim from "this token is refused", and both are worth making.
 */

/** Everything the pipeline surface offers, all of which staff may use. */
const STAFF_ALLOWED_NAV = ['Overview', 'Orders']
const STAFF_FORBIDDEN_NAV = [
  'Products',
  'Inventory',
  'Coupons',
  'Reviews',
  'Customers',
  'Settings',
]

test('staff may read the pipeline and move an order through it', async ({ request }) => {
  const staff = fixture('staff')
  expect(staff.role).toBe('staff')

  const list = await request.get('/api/v1/admin/orders/', {
    headers: bearer(staff.access),
  })
  expect(list.status(), await list.text()).toBe(200)

  const order = fixture('order', ['--payment', 'online'])

  const detail = await request.get(`/api/v1/admin/orders/${order.reference}/`, {
    headers: bearer(staff.access),
  })
  expect(detail.status(), await detail.text()).toBe(200)

  const moved = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(staff.access),
    data: { status: 'confirmed', note: 'Confirmed by fulfilment staff' },
  })
  expect(moved.status(), await moved.text()).toBe(200)
  expect((await moved.json()).status).toBe('confirmed')

  // Attaching a courier is part of moving an order, so it is staff work too.
  const packed = await request.post(`/api/v1/admin/orders/${order.reference}/status/`, {
    headers: bearer(staff.access),
    data: { status: 'packed' },
  })
  expect(packed.status(), await packed.text()).toBe(200)

  const shipment = await request.post(
    `/api/v1/admin/orders/${order.reference}/shipment/`,
    {
      headers: bearer(staff.access),
      data: { courier_name: 'Pathao', tracking_number: 'PA-0001' },
    },
  )
  expect(shipment.status(), await shipment.text()).toBe(200)

  // The audit trail names the person, not just the role.
  const truth = await (
    await request.get(`/api/v1/admin/orders/${order.reference}/`, {
      headers: bearer(staff.access),
    })
  ).json()
  const confirmation = truth.timeline.find((entry) => entry.to_status === 'confirmed')
  expect(confirmation.actor_email).toBe(staff.email)
  expect(confirmation.actor_role).toBe('admin') // the transition's actor class
})

test('every other admin surface refuses staff with 403', async ({ request }) => {
  const staff = fixture('staff')
  const admin = tokensFor(SEEDED_ADMIN.email)

  for (const endpoint of ADMIN_ONLY_ENDPOINTS) {
    const refused = await request[endpoint.method](endpoint.path, {
      headers: bearer(staff.access),
    })
    // The body is in the message on purpose: a bare "expected 403, got 500"
    // says nothing, and on this shared dev database a 500 is usually MySQL
    // refusing another connection rather than the gate misbehaving.
    expect(
      refused.status(),
      `staff GET ${endpoint.path} -> ${await refused.text()}`,
    ).toBe(403)

    // The same call as the owner, to prove the endpoint exists and answers --
    // a 403 against a route that 404s for everybody would prove nothing.
    const allowed = await request[endpoint.method](endpoint.path, {
      headers: bearer(admin.access),
    })
    expect(
      allowed.status(),
      `admin GET ${endpoint.path} -> ${await allowed.text()}`,
    ).toBe(200)

    // And anonymously: 401, not 403. "Who are you" comes before "may you".
    const anonymous = await request[endpoint.method](endpoint.path)
    expect(
      anonymous.status(),
      `anonymous GET ${endpoint.path} -> ${await anonymous.text()}`,
    ).toBe(401)
  }
})

test('staff writes are refused before a body is even validated', async ({ request }) => {
  const staff = fixture('staff')

  for (const endpoint of ADMIN_ONLY_WRITES) {
    const refused = await request[endpoint.method](endpoint.path, {
      headers: bearer(staff.access),
      data: endpoint.data,
    })
    // A gate that only covered reads would be a gate that let staff edit the
    // catalogue and move stock. Permission is checked before validation, which
    // is why an empty payload is enough to make the point.
    expect(
      refused.status(),
      `staff ${endpoint.method.toUpperCase()} ${endpoint.path} -> ${await refused.text()}`,
    ).toBe(403)
  }
})

test('the admin nav offers a staff account nothing it cannot use', async ({ page }) => {
  const problems = watchConsole(page)
  const staff = fixture('staff')

  // The real form: proving the account authenticates is a separate claim from
  // proving its token is refused somewhere.
  await signInWithForm(page, { email: staff.email, password: staff.password })
  await page.goto('/admin')

  const nav = page.getByRole('navigation', { name: 'Admin sections' })
  for (const label of STAFF_ALLOWED_NAV) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toBeVisible()
  }
  for (const label of STAFF_FORBIDDEN_NAV) {
    await expect(nav.getByRole('link', { name: label, exact: true })).toHaveCount(0)
  }

  // The overview is the owner's report, so staff get a signpost to the work
  // that IS theirs instead of a screen of refusals.
  await expect(page.getByRole('heading', { name: 'Orders are your desk' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Go to orders' })).toBeVisible()

  expect(problems, problems.join('\n')).toEqual([])
})

test('a staff account skips the dashboard request rather than firing it into a 403', async ({
  page,
  baseURL,
}) => {
  const staff = fixture('staff')
  const attempted = []
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/admin/dashboard/')) attempted.push(request.url())
  })

  await useSession(page, baseURL, staff)
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Orders are your desk' })).toBeVisible()

  // The answer is already known from the role, so asking is a round trip spent
  // on a refusal. Not a security property -- a courtesy, and a cheap one.
  expect(attempted).toEqual([])
})

test('a staff account reaching an admin-only screen by URL gets a refusal, not a blank page', async ({
  page,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const staff = fixture('staff')
  await useSession(page, baseURL, staff)

  for (const path of [
    '/admin/products',
    '/admin/products/new',
    '/admin/inventory',
    '/admin/coupons',
    '/admin/reviews',
    '/admin/settings',
  ]) {
    await page.goto(path)

    await expect(
      page.getByRole('heading', { name: 'Restricted to the store owner' }),
      `no refusal rendered at ${path}`,
    ).toBeVisible()
    await expect(page.getByRole('link', { name: 'Go to orders' })).toBeVisible()
    // Still inside the dashboard, with the work they CAN do one click away.
    await expect(
      page.getByRole('navigation', { name: 'Admin sections' }).getByRole('link', {
        name: 'Orders',
        exact: true,
      }),
    ).toBeVisible()
  }

  // Nothing threw on the way. A guard that crashes is a guard that leaks a
  // stack trace instead of an explanation.
  expect(problems, problems.join('\n')).toEqual([])
})

test('/admin/customers is advertised in the owner nav but has no screen behind it', async ({
  page,
  baseURL,
}) => {
  const admin = tokensFor(SEEDED_ADMIN.email)
  await useSession(page, baseURL, admin)

  await page.goto('/admin')
  const nav = page.getByRole('navigation', { name: 'Admin sections' })
  await expect(nav.getByRole('link', { name: 'Customers', exact: true })).toBeVisible()

  await nav.getByRole('link', { name: 'Customers', exact: true }).click()

  /*
   * Current behaviour, pinned deliberately rather than asserted as correct.
   *
   * `GET /api/v1/admin/customers/` exists and answers the owner (the matrix
   * above proves it), and AdminLayout draws a nav entry for it, but
   * routes/index.jsx has no `customers` route -- so the entry lands on the
   * admin group's `*` fallback. The 404 page is the graceful outcome the
   * router comment intends for a screen that has not shipped; what is wrong
   * is advertising a link to it in the meantime. If the screen lands, this
   * test is the one to invert.
   */
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible()
})

test('a plain customer is bounced off /admin and refused by the admin API', async ({
  page,
  request,
}) => {
  const problems = watchConsole(page)

  await signInWithForm(page, SEEDED_CUSTOMER)
  await page.goto('/admin')

  // Bounced to the storefront, not to /login: they ARE signed in, they are
  // simply not staff.
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('navigation', { name: 'Admin sections' })).toHaveCount(0)

  const customer = tokensFor(SEEDED_CUSTOMER.email)
  expect(customer.role).toBe('customer')

  // The pipeline itself, which is the one surface staff may read. A customer
  // may not, and that is the API's answer, not the router's.
  const orders = await request.get('/api/v1/admin/orders/', {
    headers: bearer(customer.access),
  })
  expect(orders.status(), await orders.text()).toBe(403)

  for (const endpoint of ADMIN_ONLY_ENDPOINTS) {
    const refused = await request[endpoint.method](endpoint.path, {
      headers: bearer(customer.access),
    })
    expect(
      refused.status(),
      `customer GET ${endpoint.path} -> ${await refused.text()}`,
    ).toBe(403)
  }

  expect(problems, problems.join('\n')).toEqual([])
})

test("one customer cannot read another's order, and is told 404 rather than 403", async ({
  request,
}) => {
  // A miss must not confirm the record exists (PRD §10.2). The admin surface
  // is the one place a reference is discoverable, so this is the natural
  // place to check the storefront's answer to a reference from it.
  const other = fixture('order', ['--payment', 'cod'])
  const customer = fixture('customer')

  const response = await request.get(`/api/v1/orders/${other.reference}/`, {
    headers: bearer(customer.access),
  })
  expect(response.status()).toBe(404)
})
