import { expect, test } from '@playwright/test'

import {
  SEEDED_ADMIN,
  bearer,
  fixture,
  tokensFor,
  useSession,
  watchConsole,
} from './_support.js'

/*
 * Review moderation, from the queue to the shop window (US-A6, FR-REV-4/5).
 *
 * The rule under test is one sentence long and has three consequences, all of
 * which are checked here from both ends: **only an approved review is
 * published, and only an approved review counts toward the rating.** So a
 * pending review is invisible on the storefront and contributes nothing;
 * approving it publishes it and moves `rating_avg`; rejecting it takes both
 * back.
 *
 * The fixture mints its own product, its own buyer and its own delivered
 * order — reviews require a delivered purchase (FR-REV-2), enforced in the
 * service — so the product starts with no approved reviews at all. That is
 * what lets this assert on the rating exactly (0.00 → 5.00 → 0.00) instead of
 * on a global average that moves whenever anybody else's test runs.
 */

async function storefrontReviews(request, slug) {
  const response = await request.get(`/api/v1/products/${slug}/reviews/`)
  expect(response.status(), await response.text()).toBe(200)
  return response.json()
}

async function storefrontProduct(request, slug) {
  const response = await request.get(`/api/v1/products/${slug}/`)
  expect(response.status(), await response.text()).toBe(200)
  return response.json()
}

test('a pending review is invisible; approving publishes it and moves the rating; rejecting takes both back', async ({
  page,
  request,
  baseURL,
}) => {
  const problems = watchConsole(page)
  const admin = tokensFor(SEEDED_ADMIN.email)
  const seeded = fixture('pending-review', ['--rating', '5'])

  expect(seeded.review_status).toBe('pending')
  expect(seeded.rating_count).toBe(0)

  // --- 1. pending: nothing on the storefront ------------------------------
  {
    const listed = await storefrontReviews(request, seeded.product_slug)
    expect(listed.count).toBe(0)
    expect(listed.summary.rating_count).toBe(0)

    const product = await storefrontProduct(request, seeded.product_slug)
    expect(product.rating_count).toBe(0)
    expect(Number(product.rating_avg ?? 0)).toBe(0)
  }

  await page.goto(seeded.storefront_url)
  const reviews = page.locator('#reviews')
  await expect(reviews).toBeVisible()
  await expect(reviews.getByText(seeded.review_title)).toHaveCount(0)
  await expect(reviews.getByText('No published reviews yet')).toBeVisible()

  // --- 2. approve ---------------------------------------------------------
  await useSession(page, baseURL, admin)
  await page.goto('/admin/reviews')
  await expect(page.getByRole('heading', { name: 'Reviews', level: 1 })).toBeVisible()

  // The queue defaults to what is waiting, which is what the screen is for.
  await expect(page.getByRole('button', { name: 'Awaiting moderation' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  const card = page.getByRole('listitem').filter({ hasText: seeded.review_title })
  await expect(card).toHaveCount(1)
  await expect(card).toContainText('pending')
  // The proving order is on the row, because "did they really buy it" is the
  // first question a moderator has.
  await expect(card).toContainText(seeded.order_reference)
  await card.getByRole('button', { name: 'Approve' }).click()

  // It leaves the pending queue, because the queue is what is still waiting.
  await expect(
    page.getByRole('listitem').filter({ hasText: seeded.review_title }),
  ).toHaveCount(0)

  {
    const listed = await storefrontReviews(request, seeded.product_slug)
    expect(listed.count).toBe(1)
    expect(listed.results[0].title).toBe(seeded.review_title)
    expect(listed.summary.rating_count).toBe(1)
    expect(listed.summary.rating_avg).toBe('5.00')

    const product = await storefrontProduct(request, seeded.product_slug)
    // The denormalised columns on Product are written by the same service the
    // moderation endpoint calls, so the figure beside the product name and
    // the figure above the reviews cannot disagree (FR-REV-5).
    expect(product.rating_count).toBe(1)
    expect(product.rating_avg).toBe('5.00')
  }

  await page.goto(seeded.storefront_url)
  await expect(reviews.getByText(seeded.review_title)).toBeVisible()
  await expect(reviews.getByText('Showing 1 review')).toBeVisible()
  await expect(reviews.getByText('Based on 1 review')).toBeVisible()
  // Derived server-side from the delivered order that proved eligibility --
  // never a flag the request could set (FR-REV-6).
  await expect(reviews.getByText('Verified Purchase')).toBeVisible()

  // --- 3. reject ----------------------------------------------------------
  /*
   * Found through the "Approved" tab rather than "Everything".
   *
   * The queue is oldest-first, deliberately -- it drains in the order
   * customers wrote it (services/reviews.moderation_queue) -- and it pages at
   * 24. So on the unfiltered tab the review just approved is the LAST of
   * everything ever written, which is not page one. Narrowing to `approved`
   * is what keeps this an assertion about moderation rather than about how
   * many reviews the dev database happens to hold.
   */
  await page.goto('/admin/reviews')
  await page.getByRole('button', { name: 'Approved' }).click()

  const moderated = page.getByRole('listitem').filter({ hasText: seeded.review_title })
  await expect(moderated).toHaveCount(1)
  await expect(moderated).toContainText('approved')
  // Approving an approved review is not an action, so it is not offered.
  await expect(moderated.getByRole('button', { name: 'Approve' })).toBeDisabled()

  await moderated.getByRole('button', { name: 'Reject' }).click()
  // It leaves the approved list, which is the visible half of "it no longer
  // counts". The invisible half is asserted against the server below.
  await expect(
    page.getByRole('listitem').filter({ hasText: seeded.review_title }),
  ).toHaveCount(0)

  const moderatedRow = await (
    await request.get('/api/v1/admin/reviews/', {
      headers: bearer(admin.access),
      params: { status: 'rejected', page_size: 100 },
    })
  ).json()
  const mine = moderatedRow.results.find((row) => row.id === seeded.review_id)
  expect(mine, 'the rejected review is not in the rejected queue').toBeTruthy()
  expect(mine.status).toBe('rejected')
  // Who rejected it, and when. Moderation is an accountable act.
  expect(mine.moderated_by_email).toBe(SEEDED_ADMIN.email)
  expect(mine.moderated_at).toBeTruthy()

  {
    const listed = await storefrontReviews(request, seeded.product_slug)
    expect(listed.count).toBe(0)
    expect(listed.summary.rating_count).toBe(0)

    const product = await storefrontProduct(request, seeded.product_slug)
    expect(product.rating_count).toBe(0)
    expect(Number(product.rating_avg ?? 0)).toBe(0)
  }

  await page.goto(seeded.storefront_url)
  await expect(reviews.getByText(seeded.review_title)).toHaveCount(0)
  await expect(reviews.getByText('No published reviews yet')).toBeVisible()

  expect(problems, problems.join('\n')).toEqual([])
})

test('moderation is the only way a review becomes visible, and it is admin-gated', async ({
  request,
}) => {
  const seeded = fixture('pending-review', ['--rating', '4'])

  // Anonymous: 401, and the review stays exactly where it was.
  const anonymous = await request.post(
    `/api/v1/admin/reviews/${seeded.review_id}/moderate/`,
    { data: { decision: 'approve' } },
  )
  expect(anonymous.status()).toBe(401)

  const staff = fixture('staff')
  const asStaff = await request.post(
    `/api/v1/admin/reviews/${seeded.review_id}/moderate/`,
    { headers: bearer(staff.access), data: { decision: 'approve' } },
  )
  // Staff may move orders. Publishing a customer's words is not theirs to do.
  expect(asStaff.status()).toBe(403)

  const listed = await storefrontReviews(request, seeded.product_slug)
  expect(listed.count).toBe(0)
  expect(listed.summary.rating_count).toBe(0)
})
