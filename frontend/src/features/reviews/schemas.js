import { z } from 'zod'

/*
 * Mirrors ReviewInputSerializer / ReviewUpdateSerializer in
 * apps/reviews/serializers.py, whose bounds come from services/reviews.py
 * (RATING_MIN/MAX, MAX_TITLE_LENGTH, MAX_BODY_LENGTH).
 *
 * This copy is a convenience so a shopper is told about a 4001-character body
 * before the round trip. The server validates all of it again, and the server
 * is the one that decides.
 */

export const RATING_MIN = 1
export const RATING_MAX = 5
export const MAX_TITLE_LENGTH = 150
export const MAX_BODY_LENGTH = 4000

/** The word beside the number, so a rating is never conveyed by stars alone. */
export const RATING_LABELS = {
  1: 'Poor',
  2: 'Fair',
  3: 'Good',
  4: 'Very good',
  5: 'Excellent',
}

const RATING_MESSAGE = 'Choose a rating from 1 to 5 stars.'

export const reviewSchema = z.object({
  /*
   * A radio group hands back the string "4", so the conversion happens here
   * rather than through register's `valueAsNumber` -- that option is
   * documented for number inputs, and relying on it for radios would make the
   * whole control depend on undocumented behaviour. Nothing selected is
   * `undefined`, which must read as "choose a rating" and not as a type
   * error, so it is mapped through rather than coerced to NaN.
   */
  rating: z.preprocess(
    (value) =>
      value === '' || value === null || value === undefined ? undefined : Number(value),
    z
      .number({ required_error: RATING_MESSAGE, invalid_type_error: RATING_MESSAGE })
      .int(RATING_MESSAGE)
      .min(RATING_MIN, RATING_MESSAGE)
      .max(RATING_MAX, RATING_MESSAGE),
  ),
  // Both optional (FR-REV-1): a rating on its own is a complete review.
  title: z
    .string()
    .max(MAX_TITLE_LENGTH, `Keep the headline under ${MAX_TITLE_LENGTH} characters.`)
    .optional(),
  body: z
    .string()
    .max(MAX_BODY_LENGTH, `Keep your review under ${MAX_BODY_LENGTH} characters.`)
    .optional(),
})
