import { Link } from 'react-router-dom'

import { useCategories } from '@/features/catalog/api'

/*
 * Site footer.
 *
 * The department column is built from the live category tree rather than a
 * hardcoded list, for the same reason the mega-menu is: a category added in
 * the admin should appear everywhere the taxonomy is shown, without a code
 * change.
 *
 * The static columns are genuinely static -- they are policy and contact
 * links, and inventing a data model for six hrefs would be worse than
 * writing them here.
 */

const HELP_LINKS = [
  { label: 'Delivery information', to: '/pages/delivery' },
  { label: 'Warranty and returns', to: '/pages/warranty' },
  { label: 'Payment methods', to: '/pages/payment' },
  { label: 'Contact us', to: '/pages/contact' },
]

const COMPANY_LINKS = [
  { label: 'About MicroMart', to: '/pages/about' },
  { label: 'Terms and conditions', to: '/pages/terms' },
  { label: 'Privacy policy', to: '/pages/privacy' },
]

const SHOP_LINKS = [
  { label: 'Today’s offers', to: '/offers' },
  { label: 'PC Builder', to: '/pc-builder' },
  { label: 'Compare products', to: '/compare' },
  { label: 'All brands', to: '/brands' },
]

function Column({ title, children }) {
  return (
    <div>
      <h2 className="mb-3 text-sm font-semibold text-white">{title}</h2>
      {children}
    </div>
  )
}

function LinkList({ links }) {
  return (
    <ul className="space-y-1">
      {links.map((link) => (
        <li key={link.to}>
          <Link
            to={link.to}
            className="flex min-h-[32px] items-center text-sm text-ink-inverse hover:text-white hover:underline"
          >
            {link.label}
          </Link>
        </li>
      ))}
    </ul>
  )
}

export default function StorefrontFooter() {
  const { data: categories } = useCategories()
  const departments = (categories ?? []).slice(0, 8)

  return (
    <footer className="mt-10 bg-chrome text-ink-inverse">
      {/* Service promises. Each one is a claim this store can actually keep. */}
      <div className="border-b border-white/10">
        <div className="mx-auto grid max-w-7xl gap-4 px-4 py-6 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ['Nationwide delivery', 'Dhaka in 24-48 hours, the rest of Bangladesh in 2-4 days.'],
            ['Cash on delivery', 'Pay when it reaches you, or online with bKash, Nagad or a card.'],
            ['Official warranty', 'Every product carries the manufacturer’s warranty.'],
            ['Real support', 'Talk to someone who knows the products, not a script.'],
          ].map(([title, body]) => (
            <div key={title} className="flex gap-3">
              <span
                aria-hidden="true"
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-pill bg-white/10 text-brand"
              >
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none"
                     stroke="currentColor" strokeWidth="2">
                  <path d="M4 12.5l5 5L20 6.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
              <div>
                <p className="text-sm font-semibold text-white">{title}</p>
                <p className="mt-0.5 text-xs leading-relaxed">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-8 sm:grid-cols-2 lg:grid-cols-5">
        <div className="sm:col-span-2 lg:col-span-1">
          <Link to="/" className="flex items-center gap-1.5 text-lg font-semibold text-white">
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-6 w-6 text-brand"
                 fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M12 2.5l8 4.6v9.8l-8 4.6-8-4.6V7.1z" strokeLinejoin="round" />
              <path d="M8 15V9l4 4 4-4v6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Micro<span className="text-brand">Mart</span>
          </Link>
          <p className="mt-3 text-sm leading-relaxed">
            Computers, components and electronics, delivered across Bangladesh.
          </p>
          <address className="mt-3 not-italic text-sm">
            <a href="tel:+8809600000000" className="block hover:text-white hover:underline">
              &#2547; 09600 000 000
            </a>
            <a
              href="mailto:support@micromart.example"
              className="block hover:text-white hover:underline"
            >
              support@micromart.example
            </a>
          </address>
        </div>

        <Column title="Shop">
          <LinkList links={SHOP_LINKS} />
        </Column>

        <Column title="Departments">
          <ul className="space-y-1">
            {departments.map((category) => (
              <li key={category.id}>
                <Link
                  to={`/c/${category.slug}`}
                  className="flex min-h-[32px] items-center text-sm text-ink-inverse hover:text-white hover:underline"
                >
                  {category.name}
                </Link>
              </li>
            ))}
          </ul>
        </Column>

        <Column title="Help">
          <LinkList links={HELP_LINKS} />
        </Column>

        <Column title="Company">
          <LinkList links={COMPANY_LINKS} />
        </Column>
      </div>

      <div className="border-t border-white/10">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-4 text-xs sm:flex-row sm:items-center sm:justify-between">
          <p>&copy; {new Date().getFullYear()} MicroMart.</p>
        </div>
      </div>
    </footer>
  )
}
