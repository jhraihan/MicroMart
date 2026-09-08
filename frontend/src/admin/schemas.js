import { z } from 'zod'

// Client-side form schemas for the admin screens.

const MONEY = /^\d{1,10}(\.\d{1,2})?$/
const WHOLE = /^\d+$/

const money = (label = 'Enter an amount like 62500.00') =>
  z.string().trim().regex(MONEY, label)

const optionalMoney = (label = 'Enter an amount like 62500.00, or leave it blank.') =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || MONEY.test(value), label)

const optionalWhole = (label) =>
  z
    .string()
    .trim()
    .refine((value) => value === '' || WHOLE.test(value), `${label} must be a whole number.`)

// ---------------------------------------------------------------------------
// Products (US-A2)
// ---------------------------------------------------------------------------
export const specSchema = z.object({
  key: z.string().trim().max(120, 'Keep the label under 120 characters.'),
  value: z.string().trim().max(500, 'Keep the value under 500 characters.'),
})

export const variantFieldsSchema = z.object({
  sku: z.string().trim().min(1, 'SKU is required.').max(64, 'Keep the SKU under 64 characters.'),
  option_label: z.string().trim().max(120, 'Keep the option label under 120 characters.'),
  price: money(),
  compare_at_price: optionalMoney(),
  low_stock_threshold: optionalWhole('The low-stock threshold'),
  weight_grams: optionalWhole('Weight'),
  is_active: z.boolean(),
})

/**
 * A variant on the *create* form carries an opening stock quantity.
 *
 * This is the only place a stock number rides along with a variant, and the
 * server writes it through the inventory ledger with reason `initial` so the
 * variant reconciles from birth. Editing a variant later has no stock field
 * at all -- see variantFieldsSchema, which deliberately has none.
 */
export const newVariantSchema = variantFieldsSchema.extend({
  stock: optionalWhole('Opening stock'),
})

const productFields = {
  name: z.string().trim().min(1, 'Name is required.').max(255, 'Keep the name under 255 characters.'),
  slug: z
    .string()
    .trim()
    .max(280)
    .refine(
      (value) => value === '' || /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value),
      'Use lowercase letters, numbers and hyphens, or leave it blank to derive it from the name.',
    ),
  description: z.string().trim(),
  category_id: z.string().min(1, 'Choose a category.'),
  brand_id: z.string(),
  warranty_months: optionalWhole('Warranty'),
  is_active: z.boolean(),
  specs: z.array(specSchema),
}

/** A spec row is either empty or complete -- a value with no label is a typo. */
function checkSpecs(values, ctx) {
  values.specs?.forEach((row, index) => {
    if (row.value.trim() && !row.key.trim()) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['specs', index, 'key'],
        message: 'Give this specification a label, or clear the value.',
      })
    }
  })
}

export const productEditSchema = z.object(productFields).superRefine(checkSpecs)

/**
 * Creation requires at least one variant.
 *
 * Not a UI preference: POST /admin/products/ refuses an empty list with
 * PRODUCT_REQUIRES_VARIANT rather than inventing a default, because a
 * server-invented SKU and price could later be snapshotted onto a real order
 * line. A product with no options simply sends one variant with a blank
 * option label.
 */
export const productCreateSchema = z
  .object({ ...productFields, variants: z.array(newVariantSchema).min(1, 'Add at least one variant.') })
  .superRefine(checkSpecs)

// ---------------------------------------------------------------------------
// Inventory (US-A4)
// ---------------------------------------------------------------------------
export const ADJUSTMENT_REASONS = [
  { value: 'restock', label: 'Restock — stock arrived' },
  { value: 'manual_adjustment', label: 'Manual adjustment — recount or correction' },
  { value: 'damage', label: 'Damage or loss' },
]

/**
 * `reason` is mandatory (FR-INV-8) and cannot be one of the order-driven
 * reasons: `order_confirmed`, `order_cancelled` and `initial` are written by
 * the order state machine, by variant creation and by the importer, and a
 * hand-typed one would put a movement in the ledger no order can account for.
 */
export const adjustmentSchema = z.object({
  delta: z
    .string()
    .trim()
    .regex(/^-?\d+$/, 'Enter a whole number, negative to remove stock.')
    .refine((value) => Number(value) !== 0, 'An adjustment of zero would record nothing.'),
  reason: z.enum(['restock', 'manual_adjustment', 'damage'], {
    errorMap: () => ({ message: 'Choose why the stock is moving.' }),
  }),
  note: z.string().trim().max(255, 'Keep the note under 255 characters.'),
})

// ---------------------------------------------------------------------------
// Coupons (US-A5)
// ---------------------------------------------------------------------------
export const couponSchema = z
  .object({
    code: z
      .string()
      .trim()
      .min(3, 'A code is at least 3 characters.')
      .max(32, 'A code is at most 32 characters.')
      .regex(
        /^[A-Za-z0-9][A-Za-z0-9_-]*$/,
        'Letters, numbers, hyphens and underscores only — a shopper has to be able to type it.',
      ),
    discount_type: z.enum(['percent', 'fixed']),
    value: money('Enter the discount as a number, e.g. 10 for 10% or 500 for ৳500.'),
    max_discount: optionalMoney('Enter a cap like 1000.00, or leave it blank for no cap.'),
    min_order_value: optionalMoney('Enter a minimum like 2000.00, or leave it blank.'),
    valid_from: z.string().min(1, 'Choose when the coupon starts.'),
    valid_until: z.string().min(1, 'Choose when the coupon ends.'),
    usage_limit: optionalWhole('The total usage cap'),
    per_user_limit: z.string().trim().regex(WHOLE, 'Enter 1 or more.'),
    scope_type: z.enum(['all', 'category', 'product']),
    scope_ids: z.array(z.string()),
    is_active: z.boolean(),
  })
  .superRefine((values, ctx) => {
    // Restated from services/coupons.py so the refusal is immediate. The
    // service checks every one of them again, and its codes are what this
    // form renders when the two disagree.
    //
    // Deliberately NOT restated: "a cap on a fixed coupon is refused". The
    // cap input is disabled for a fixed coupon and the payload sends null, so
    // a value left over from switching the type must not block a submit the
    // admin has no way to unblock.
    if (values.discount_type === 'percent' && Number(values.value) > 100) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['value'],
        message: 'A percentage discount cannot exceed 100.',
      })
    }
    if (values.valid_from && values.valid_until && values.valid_until <= values.valid_from) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['valid_until'],
        message: 'The end of the window must be after its start.',
      })
    }
    if (values.usage_limit.trim() && Number(values.usage_limit) < 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['usage_limit'],
        message: 'Leave this blank for unlimited. Zero would mean nobody.',
      })
    }
    if (Number(values.per_user_limit) < 1) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['per_user_limit'],
        message: 'Enter 1 or more. Zero would be read as unlimited, which is the opposite.',
      })
    }
    if (values.scope_type !== 'all' && values.scope_ids.length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['scope_ids'],
        message: 'Choose what this coupon applies to.',
      })
    }
  })

// ---------------------------------------------------------------------------
// Store settings
// ---------------------------------------------------------------------------
export const settingsSchema = z.object({
  store_name: z.string().trim().min(1, 'The store needs a name.').max(120),
  support_email: z
    .string()
    .trim()
    .refine(
      (value) => value === '' || z.string().email().safeParse(value).success,
      'Enter a valid email address, or leave it blank.',
    ),
  support_phone: z.string().trim().max(20, 'Keep the phone number under 20 characters.'),
  tax_rate: z
    .string()
    .trim()
    .regex(/^\d{1,3}(\.\d{1,2})?$/, 'Enter the VAT rate as a percentage, e.g. 15.00.')
    .refine((value) => Number(value) <= 100, 'The VAT rate must be between 0 and 100 percent.'),
  tax_inclusive_pricing: z.boolean(),
  cod_enabled: z.boolean(),
  cod_max_order_value: optionalMoney(
    'Enter a ceiling like 20000.00, or leave it blank to disable the cap.',
  ),
  low_stock_digest_recipients: z.string().trim(),
})
