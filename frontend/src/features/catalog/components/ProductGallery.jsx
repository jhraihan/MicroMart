import clsx from 'clsx'
import { useState } from 'react'

/*
 * Gallery for the detail page. `images` is recomputed by the page whenever
 * the selected variant changes, and the page keys this component on the
 * variant id, so a variant switch remounts the gallery back to its first
 * image -- no reset effect, no cascading render.
 */
export default function ProductGallery({ images = [], productName }) {
  const [activeIndex, setActiveIndex] = useState(0)
  const active = images[activeIndex] ?? images[0] ?? null
  const credit = active?.credit ?? null

  return (
    <div className="flex flex-col gap-3">
      <div className="relative flex aspect-square items-center justify-center overflow-hidden rounded-card bg-white p-4 shadow-el-1">
        {active?.url ? (
          <img
            src={active.url}
            alt={active.alt_text || productName}
            width={600}
            height={600}
            decoding="async"
            className="h-full w-full object-contain"
          />
        ) : (
          <span className="text-sm text-ink-muted">No image available</span>
        )}

        {credit?.is_representative && (
          <span className="absolute bottom-2 left-2 rounded-pill bg-ink/80 px-2.5 py-1 text-[11px] font-medium text-white">
            Representative image
          </span>
        )}
      </div>

      {images.length > 1 && (
        <ul className="flex gap-2 overflow-x-auto pb-1" aria-label="Product images">
          {images.map((image, index) => (
            <li key={image.id}>
              <button
                type="button"
                onClick={() => setActiveIndex(index)}
                aria-label={`Show image ${index + 1} of ${images.length}`}
                aria-current={index === activeIndex ? 'true' : undefined}
                className={clsx(
                  'flex h-16 w-16 shrink-0 items-center justify-center rounded-card border-2 bg-white p-1',
                  index === activeIndex ? 'border-action' : 'border-line hover:border-action',
                )}
              >
                <img
                  src={image.url}
                  alt=""
                  width={64}
                  height={64}
                  loading="lazy"
                  decoding="async"
                  className="h-full w-full object-contain"
                />
              </button>
            </li>
          ))}
        </ul>
      )}

      {credit && (
        <p className="text-[11px] leading-relaxed text-ink-muted">
          {credit.is_representative
            ? 'Photo shows a product of this type, not necessarily this exact model. '
            : ''}
          Image:{' '}
          <a
            href={credit.source_url}
            target="_blank"
            rel="noopener noreferrer license"
            className="underline hover:text-action"
          >
            {credit.attribution || 'Wikimedia Commons'}
          </a>{' '}
          &mdash; {credit.license}, via Wikimedia Commons.
        </p>
      )}
    </div>
  )
}
