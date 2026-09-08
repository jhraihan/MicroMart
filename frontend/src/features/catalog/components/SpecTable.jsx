// The grouped specification table.
export default function SpecTable({ product }) {
  const groups =
    product.spec_groups?.length > 0
      ? product.spec_groups
      : product.specs?.length > 0
        ? [{ group: 'Specifications', rows: product.specs }]
        : []

  if (groups.length === 0) return null

  return (
    <section
      aria-labelledby="specs-heading"
      className="rounded-card bg-white p-4 shadow-el-1"
    >
      <h2 id="specs-heading" className="mb-1 text-base font-semibold text-ink">
        Specifications
      </h2>

      <div className="divide-y divide-line">
        {groups.map((group) => (
          <div key={group.group} className="py-3 first:pt-2 last:pb-0">
            <h3 className="mb-1.5 text-sm font-semibold text-action">{group.group}</h3>
            <table className="w-full table-fixed text-sm">
              <caption className="sr-only">
                {group.group} specifications for {product.name}
              </caption>
              <tbody className="divide-y divide-line">
                {group.rows.map((row, index) => (
                  <tr key={`${row.key}-${index}`}>
                    <th
                      scope="row"
                      className="w-2/5 py-2 pr-3 text-left align-top font-medium text-ink-muted"
                    >
                      {row.key}
                    </th>
                    <td className="break-words py-2 align-top text-ink">{row.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </section>
  )
}
