import { useRef, useState } from 'react'

import { Badge, Button, Input } from '@/components/ui'
import { parseApiError } from '@/lib/api'

import {
  useDeleteProductImage,
  useReorderProductImages,
  useUploadProductImage,
} from '../api'
import { Callout, FormAlert } from './AdminUI'

// The product gallery (US-A2: "multiple images, reorderable, one primary").
export default function ImageManager({ product }) {
  const images = product.images ?? []
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [altText, setAltText] = useState('')
  const [isPrimary, setIsPrimary] = useState(false)
  const [error, setError] = useState(null)

  const upload = useUploadProductImage(product.id)
  const reorder = useReorderProductImages(product.id)
  const remove = useDeleteProductImage(product.id)

  const busy = upload.isPending || reorder.isPending || remove.isPending

  function run(mutation, payload) {
    setError(null)
    mutation.mutate(payload, { onError: (err) => setError(parseApiError(err).message) })
  }

  function submitUpload(event) {
    event.preventDefault()
    if (!file) {
      setError('Choose an image file to upload.')
      return
    }
    setError(null)
    upload.mutate(
      { file, alt_text: altText, is_primary: isPrimary },
      {
        onSuccess: () => {
          setFile(null)
          setAltText('')
          setIsPrimary(false)
          if (fileRef.current) fileRef.current.value = ''
        },
        onError: (err) => setError(parseApiError(err).message),
      },
    )
  }

  function move(index, direction) {
    const next = [...images]
    const target = index + direction
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    // `primary_id` is deliberately absent: this is a reorder, not a change of
    // which photo represents the product.
    run(reorder, { order: next.map((image) => image.id) })
  }

  function makePrimary(imageId) {
    run(reorder, { order: images.map((image) => image.id), primary_id: imageId })
  }

  return (
    <section aria-labelledby="images-heading" className="rounded-card border border-line bg-white p-4">
      <h2 id="images-heading" className="text-base font-semibold text-ink">
        Images
      </h2>
      <p className="mt-1 max-w-prose text-sm text-ink-muted">
        The primary image is the one shown on cards, search results and the
        cart. Exactly one image is primary while the gallery has any.
      </p>

      <FormAlert message={error} />

      {images.length === 0 ? (
        <p className="my-4 rounded-card border border-dashed border-line px-4 py-6 text-center text-sm text-ink-muted">
          No images yet. The first one uploaded becomes the primary.
        </p>
      ) : (
        <ul className="my-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {images.map((image, index) => (
            <li
              key={image.id}
              className="flex flex-col gap-2 rounded-card border border-line p-3"
            >
              <div className="flex items-start gap-3">
                <img
                  src={image.url}
                  alt={image.alt_text || `Gallery image ${index + 1}`}
                  className="h-20 w-20 shrink-0 rounded-card border border-line object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-ink-muted">Position {index + 1}</p>
                  <p className="truncate text-sm text-ink">
                    {image.alt_text || <span className="text-ink-muted">No alt text</span>}
                  </p>
                  {image.is_primary && (
                    <Badge tone="action" size="sm" className="mt-1">
                      Primary
                    </Badge>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || index === 0}
                  aria-label={`Move image ${index + 1} earlier`}
                  onClick={() => move(index, -1)}
                >
                  ← Earlier
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || index === images.length - 1}
                  aria-label={`Move image ${index + 1} later`}
                  onClick={() => move(index, 1)}
                >
                  Later →
                </Button>
                {!image.is_primary && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    aria-label={`Make image ${index + 1} the primary image`}
                    onClick={() => makePrimary(image.id)}
                  >
                    Make primary
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`Remove image ${index + 1}`}
                  onClick={() => run(remove, image.id)}
                >
                  Remove
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submitUpload} className="grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="product-image-file" className="text-sm font-medium text-ink">
            Add an image
          </label>
          <input
            id="product-image-file"
            ref={fileRef}
            type="file"
            accept="image/*"
            aria-describedby="product-image-file-hint"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="min-h-[44px] w-full rounded-card border border-line bg-white px-3 py-2 text-sm text-ink"
          />
          <p id="product-image-file-hint" className="text-xs text-ink-muted">
            JPEG, PNG or WebP, up to 5 MB. The file is verified server-side, so
            a renamed document is refused.
          </p>
        </div>
        <Input
          label="Alt text"
          value={altText}
          onChange={(event) => setAltText(event.target.value)}
          hint="Describe the photo for a shopper using a screen reader."
        />
        <label className="flex min-h-[44px] items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-action"
            checked={isPrimary}
            onChange={(event) => setIsPrimary(event.target.checked)}
          />
          Make this the primary image
        </label>
        <div className="flex items-end justify-end">
          <Button type="submit" loading={upload.isPending} disabled={busy && !upload.isPending}>
            Upload image
          </Button>
        </div>
      </form>

      <Callout tone="info" className="mt-4">
        Removing an image deletes the file — nothing snapshots it onto an
        order. If the primary is removed, the next image in order inherits the
        flag.
      </Callout>
    </section>
  )
}
