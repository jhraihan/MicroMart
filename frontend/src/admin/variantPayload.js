// Turn a variant form's string fields into the API's body.
export function variantPayload(values, { withStock = false } = {}) {
  const payload = {
    sku: values.sku.trim(),
    option_label: values.option_label.trim(),
    price: values.price.trim(),
    compare_at_price: values.compare_at_price.trim() || null,
    is_active: values.is_active,
  }
  if (values.low_stock_threshold.trim()) {
    payload.low_stock_threshold = Number(values.low_stock_threshold)
  }
  if (values.weight_grams.trim()) payload.weight_grams = Number(values.weight_grams)
  if (withStock && values.stock?.trim()) payload.stock = Number(values.stock)
  return payload
}
