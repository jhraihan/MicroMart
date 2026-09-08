import { z } from 'zod'

/*
 * Mirrors the POST /orders/ body in
 * docs/api-contract-cart-checkout-orders.md. Client validation is a UX
 * convenience that keeps the round trip short and puts the message next to
 * the field it belongs to (FR-CHK acceptance: per-field messages, not one
 * generic banner). The server revalidates everything and stays authoritative.
 *
 * Notably absent: any total. The client never submits money.
 */

// 01[3-9]XXXXXXXX, with or without the +880 country code (FR-CHK-3). The
// server normalises before storage; this only decides whether to let the
// request leave.
const phone = z
  .string()
  .trim()
  .regex(/^(?:\+?880|0)1[3-9]\d{8}$/, 'Enter a valid Bangladeshi mobile number.')

const optionalText = (max) =>
  z.string().trim().max(max, `Keep this under ${max} characters.`).optional().or(z.literal(''))

export const checkoutSchema = z
  .object({
    // --- Contact (guests included, FR-CHK-5) ---
    email: z
      .string()
      .trim()
      .min(1, 'Email is required.')
      .email('Enter a valid email address.'),
    phone,

    // --- Shipping address (FR-CHK-2, FR-CHK-4) ---
    address_mode: z.enum(['saved', 'new']),
    address_id: z.string().optional(),
    recipient_name: z.string().trim().max(150).optional().or(z.literal('')),
    ship_phone: z.string().trim().optional().or(z.literal('')),
    division: z.string().optional().or(z.literal('')),
    district: z.string().optional().or(z.literal('')),
    upazila: optionalText(64),
    area: optionalText(128),
    street: z.string().trim().max(255).optional().or(z.literal('')),
    postcode: optionalText(12),
    save_address: z.boolean().optional(),

    // --- Payment and note ---
    payment_method: z.enum(['cod', 'online'], {
      errorMap: () => ({ message: 'Choose how you want to pay.' }),
    }),
    note: optionalText(500),
  })
  .superRefine((values, ctx) => {
    if (values.address_mode === 'saved') {
      if (!values.address_id) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['address_id'],
          message: 'Choose a saved address, or add a new one.',
        })
      }
      return
    }

    const required = [
      ['recipient_name', 'Recipient name is required.'],
      ['division', 'Choose a division.'],
      ['district', 'Choose a district.'],
      ['street', 'Street address is required.'],
    ]
    for (const [field, message] of required) {
      if (!values[field]) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, path: [field], message })
      }
    }

    const result = phone.safeParse(values.ship_phone ?? '')
    if (!result.success) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['ship_phone'],
        message: 'Enter a valid Bangladeshi mobile number for delivery.',
      })
    }
  })

/** Build the POST /orders/ body. Totals are never part of it. */
export function toOrderPayload(values, { items, couponCode, idempotencyKey, isAuthenticated }) {
  const payload = {
    idempotency_key: idempotencyKey,
    items,
    email: values.email.trim(),
    phone: values.phone.trim(),
    payment_method: values.payment_method,
    coupon_code: couponCode || null,
    note: values.note?.trim() || '',
  }

  if (isAuthenticated && values.address_mode === 'saved') {
    payload.address_id = Number(values.address_id)
    payload.shipping_address = null
  } else {
    payload.address_id = null
    payload.shipping_address = {
      recipient_name: values.recipient_name.trim(),
      phone: values.ship_phone.trim(),
      division: values.division,
      district: values.district,
      upazila: values.upazila?.trim() || '',
      area: values.area?.trim() || '',
      street: values.street.trim(),
      postcode: values.postcode?.trim() || '',
    }
    if (isAuthenticated) payload.save_address = Boolean(values.save_address)
  }

  return payload
}
