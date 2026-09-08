import clsx from 'clsx'

import StarRating from '@/features/catalog/components/StarRating'

/*
 * One review's score.
 *
 * The stars are decorative (StarRating already marks them aria-hidden and
 * carries the whole rating as an sr-only sentence). Beside them sits a
 * *visible* "4/5", so the score survives greyscale, a colour-vision
 * difference, and a failed icon paint -- colour is never the only signal
 * (PRD §9.3).
 */
export default function ReviewStars({ rating, size = 'sm', className }) {
  const value = Number(rating) || 0

  return (
    <span className={clsx('inline-flex items-center gap-1.5', className)}>
      <StarRating
        value={value}
        size={size}
        showCount={false}
        label={`Rated ${value} out of 5`}
      />
      <span aria-hidden="true" className="text-xs font-semibold text-ink-muted">
        {value}/5
      </span>
    </span>
  )
}
