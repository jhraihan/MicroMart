// Document head management for an SPA.
import { useEffect } from 'react'

const SITE_NAME = 'MicroMart'
const DEFAULT_DESCRIPTION =
  'Computers, components and electronics in Bangladesh. Genuine products, official warranty, cash on delivery nationwide.'

/** Absolute URL for a path, used for canonical and og:url. */
export function absoluteUrl(path = '') {
  if (typeof window === 'undefined') return path
  return new URL(path || window.location.pathname, window.location.origin).toString()
}

function upsertMeta(selector, attrs) {
  let element = document.head.querySelector(selector)
  let created = false
  if (!element) {
    element = document.createElement('meta')
    created = true
  }
  const previous = {}
  Object.entries(attrs).forEach(([key, value]) => {
    previous[key] = element.getAttribute(key)
    if (value == null) element.removeAttribute(key)
    else element.setAttribute(key, value)
  })
  if (created) document.head.appendChild(element)
  return () => {
    if (created) {
      element.remove()
      return
    }
    Object.entries(previous).forEach(([key, value]) => {
      if (value == null) element.removeAttribute(key)
      else element.setAttribute(key, value)
    })
  }
}

function upsertLink(rel, href) {
  let element = document.head.querySelector(`link[rel="${rel}"]`)
  let created = false
  if (!element) {
    element = document.createElement('link')
    element.setAttribute('rel', rel)
    created = true
  }
  const previous = element.getAttribute('href')
  if (href) element.setAttribute('href', href)
  if (created) document.head.appendChild(element)
  return () => {
    if (created) element.remove()
    else if (previous) element.setAttribute('href', previous)
  }
}

/**
 * Set the page title, description, canonical URL and Open Graph tags.
 *
 * `title` is the page's own name; the site name is appended here so no caller
 * has to remember to. Pass `noIndex` for pages that must stay out of an index
 * -- search results with a keyword, and anything behind a login.
 */
export function useSeo({
  title,
  description = DEFAULT_DESCRIPTION,
  canonical,
  image,
  type = 'website',
  noIndex = false,
} = {}) {
  useEffect(() => {
    const previousTitle = document.title
    const fullTitle = title ? `${title} — ${SITE_NAME}` : SITE_NAME
    document.title = fullTitle

    const url = absoluteUrl(canonical)
    const absoluteImage = image ? absoluteUrl(image) : null

    const cleanups = [
      upsertMeta('meta[name="description"]', { name: 'description', content: description }),
      upsertLink('canonical', url),
      upsertMeta('meta[property="og:title"]', { property: 'og:title', content: fullTitle }),
      upsertMeta('meta[property="og:description"]', {
        property: 'og:description',
        content: description,
      }),
      upsertMeta('meta[property="og:type"]', { property: 'og:type', content: type }),
      upsertMeta('meta[property="og:url"]', { property: 'og:url', content: url }),
      upsertMeta('meta[property="og:site_name"]', {
        property: 'og:site_name',
        content: SITE_NAME,
      }),
      upsertMeta('meta[name="twitter:card"]', {
        name: 'twitter:card',
        content: absoluteImage ? 'summary_large_image' : 'summary',
      }),
      upsertMeta('meta[name="twitter:title"]', { name: 'twitter:title', content: fullTitle }),
      upsertMeta('meta[name="twitter:description"]', {
        name: 'twitter:description',
        content: description,
      }),
    ]

    if (absoluteImage) {
      cleanups.push(
        upsertMeta('meta[property="og:image"]', {
          property: 'og:image',
          content: absoluteImage,
        }),
        upsertMeta('meta[name="twitter:image"]', {
          name: 'twitter:image',
          content: absoluteImage,
        }),
      )
    }

    // `noindex` is only ever *added* by a page that wants it, and removed on
    // the way out -- a stale robots tag left behind would quietly deindex
    // whatever the shopper navigated to next.
    if (noIndex) {
      cleanups.push(
        upsertMeta('meta[name="robots"]', {
          name: 'robots',
          content: 'noindex, follow',
        }),
      )
    }

    return () => {
      document.title = previousTitle
      cleanups.forEach((undo) => undo())
    }
  }, [title, description, canonical, image, type, noIndex])
}

/**
 * Attach one JSON-LD block for the lifetime of a component.
 *
 * `data` must be memoised by the caller (or built inline from primitives) --
 * a fresh object every render would tear the script tag down and rebuild it
 * on every render.
 */
export function useJsonLd(data) {
  useEffect(() => {
    if (!data) return undefined
    const script = document.createElement('script')
    script.type = 'application/ld+json'
    script.textContent = JSON.stringify(data)
    document.head.appendChild(script)
    return () => script.remove()
  }, [data])
}

// ---------------------------------------------------------------------------
// Structured-data builders
//
// Kept as pure functions so they can be unit-tested and so a component never
// hand-assembles schema.org vocabulary inline.
// ---------------------------------------------------------------------------

/** schema.org/Product, including offer and aggregate rating when present. */
export function productJsonLd(product) {
  if (!product) return null

  const offers =
    product.price_min != null
      ? {
          '@type': 'Offer',
          priceCurrency: 'BDT',
          price: product.price_min,
          availability: product.in_stock
            ? 'https://schema.org/InStock'
            : 'https://schema.org/OutOfStock',
          url: absoluteUrl(`/p/${product.slug}`),
        }
      : undefined

  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: product.name,
    description: product.description || undefined,
    sku: product.variants?.[0]?.sku || undefined,
    mpn: product.model_number || undefined,
    brand: product.brand ? { '@type': 'Brand', name: product.brand.name } : undefined,
    image: product.images?.length
      ? product.images.map((img) => absoluteUrl(img.url))
      : undefined,
    offers,
    // Only emitted with real reviews behind it. A zero-count aggregate rating
    // is both meaningless and a structured-data error.
    aggregateRating:
      product.rating_count > 0
        ? {
            '@type': 'AggregateRating',
            ratingValue: product.rating_avg,
            reviewCount: product.rating_count,
          }
        : undefined,
  }
}

/** schema.org/BreadcrumbList from [{name, path}] in order. */
export function breadcrumbJsonLd(trail) {
  if (!trail?.length) return null
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: trail.map((crumb, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: crumb.name,
      item: absoluteUrl(crumb.path),
    })),
  }
}

/** schema.org/ItemList for a category or search results page. */
export function itemListJsonLd(products, { name } = {}) {
  if (!products?.length) return null
  return {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    name,
    numberOfItems: products.length,
    itemListElement: products.map((product, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      url: absoluteUrl(`/p/${product.slug}`),
      name: product.name,
    })),
  }
}

/** schema.org/Organization + the search action, for the home page. */
export function organizationJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'Organization',
    name: SITE_NAME,
    url: absoluteUrl('/'),
    description: DEFAULT_DESCRIPTION,
    areaServed: 'BD',
  }
}

export function websiteJsonLd() {
  return {
    '@context': 'https://schema.org',
    '@type': 'WebSite',
    name: SITE_NAME,
    url: absoluteUrl('/'),
    potentialAction: {
      '@type': 'SearchAction',
      target: {
        '@type': 'EntryPoint',
        urlTemplate: `${absoluteUrl('/search')}?q={search_term_string}`,
      },
      'query-input': 'required name=search_term_string',
    },
  }
}
