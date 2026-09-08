import { zodResolver } from '@hookform/resolvers/zod'
import { useForm } from 'react-hook-form'

import { Button, Input, Textarea } from '@/components/ui'
import { parseApiError } from '@/lib/api'

import { useSubmitReview, useUpdateReview } from '../api'
import { MAX_BODY_LENGTH, MAX_TITLE_LENGTH, reviewSchema } from '../schemas'
import RatingInput from './RatingInput'

// Write or edit a review (FR-REV-1, FR-REV-3).
export default function ReviewForm({ slug, review = null, onDone, onCancel }) {
  const isEdit = Boolean(review)
  const submit = useSubmitReview(slug)
  const update = useUpdateReview(slug)
  const mutation = isEdit ? update : submit

  const {
    register,
    handleSubmit,
    watch,
    setError,
    formState: { errors },
  } = useForm({
    resolver: zodResolver(reviewSchema),
    defaultValues: {
      rating: review?.rating ?? undefined,
      title: review?.title ?? '',
      body: review?.body ?? '',
    },
  })

  // The radio group's value stays a string all the way to the resolver; the
  // schema's preprocess step is the single place it becomes a number.
  const ratingRegistration = register('rating')
  const rating = watch('rating')

  function onSubmit(values) {
    const payload = {
      rating: values.rating,
      title: values.title?.trim() ?? '',
      body: values.body?.trim() ?? '',
    }
    const variables = isEdit ? { id: review.id, ...payload } : payload

    mutation.mutate(variables, {
      onSuccess: (saved) => onDone?.(saved),
      onError: (error) => {
        const { message, field } = parseApiError(error)
        // Only `rating` has a matching control; PURCHASE_REQUIRED and
        // REVIEW_ALREADY_EXISTS name `product`, and REVIEW_EDIT_WINDOW_CLOSED
        // names `review` -- neither is a field on this form, so they belong
        // at the top where they will actually be read.
        setError(field === 'rating' ? 'rating' : 'root', { message })
      },
    })
  }

  return (
    <form
      noValidate
      onSubmit={handleSubmit(onSubmit)}
      className="flex flex-col gap-4 rounded-card bg-white p-4 shadow-el-1"
    >
      <h3 className="text-base font-semibold text-ink">
        {isEdit ? 'Edit your review' : 'Write a review'}
      </h3>

      {errors.root && (
        <p role="alert" className="rounded-card bg-danger/10 px-3 py-2 text-sm text-danger">
          {errors.root.message}
        </p>
      )}

      <RatingInput
        registration={ratingRegistration}
        value={rating}
        error={errors.rating?.message}
        disabled={mutation.isPending}
      />

      <Input
        label="Headline"
        maxLength={MAX_TITLE_LENGTH}
        placeholder="Sum it up in a few words (optional)"
        error={errors.title?.message}
        disabled={mutation.isPending}
        {...register('title')}
      />

      <Textarea
        label="Your review"
        rows={5}
        maxLength={MAX_BODY_LENGTH}
        placeholder="What did you like or dislike? (optional)"
        hint="Optional — a rating on its own is a complete review."
        error={errors.body?.message}
        disabled={mutation.isPending}
        {...register('body')}
      />

      <p className="text-xs text-ink-muted">
        Reviews are checked by our team before they appear on the site.
      </p>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" loading={mutation.isPending}>
          {isEdit ? 'Save changes' : 'Submit review'}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            disabled={mutation.isPending}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}
