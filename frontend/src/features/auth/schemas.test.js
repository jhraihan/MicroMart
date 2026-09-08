import { describe, expect, it } from 'vitest'

import {
  addressSchema,
  changePasswordSchema,
  loginSchema,
  registerSchema,
} from './schemas'

function errorFor(schema, value, field) {
  const result = schema.safeParse(value)
  if (result.success) return null
  return result.error.issues.find((issue) => issue.path[0] === field)?.message ?? null
}

describe('loginSchema', () => {
  it('accepts an email and password', () => {
    const result = loginSchema.safeParse({
      email: 'shopper@example.com',
      password: 'whatever',
    })
    expect(result.success).toBe(true)
  })

  it('rejects an address that is not an email', () => {
    expect(errorFor(loginSchema, { email: 'nope', password: 'x' }, 'email')).toBeTruthy()
  })
})

describe('registerSchema', () => {
  const valid = {
    full_name: 'Jahid Raihan',
    email: 'jahid@example.com',
    phone: '01712345678',
    password: 'strongpass1',
    confirm_password: 'strongpass1',
  }

  it('accepts a complete registration', () => {
    expect(registerSchema.safeParse(valid).success).toBe(true)
  })

  it('rejects mismatched passwords', () => {
    const result = registerSchema.safeParse({ ...valid, confirm_password: 'different' })
    expect(result.success).toBe(false)
  })

  it('allows the phone number to be left out', () => {
    expect(registerSchema.safeParse({ ...valid, phone: '' }).success).toBe(true)
  })
})

describe('Bangladeshi phone numbers', () => {
  const valid = ['01712345678', '01312345678', '01912345678', '+8801712345678']
  const invalid = ['0171234567', '01212345678', '1712345678', 'not a number', '']

  it.each(valid)('accepts %s', (phone) => {
    expect(errorFor(addressSchema, { phone }, 'phone')).toBeNull()
  })

  it.each(invalid)('rejects %s', (phone) => {
    expect(errorFor(addressSchema, { phone }, 'phone')).toBeTruthy()
  })
})

describe('changePasswordSchema', () => {
  const valid = {
    current_password: 'oldpassword',
    new_password: 'newpassword1',
    confirm_password: 'newpassword1',
  }

  it('accepts a valid change', () => {
    expect(changePasswordSchema.safeParse(valid).success).toBe(true)
  })

  it('needs the current password', () => {
    expect(
      errorFor(changePasswordSchema, { ...valid, current_password: '' }, 'current_password'),
    ).toBeTruthy()
  })

  it('rejects a new password under 8 characters', () => {
    expect(
      errorFor(changePasswordSchema, { ...valid, new_password: 'short' }, 'new_password'),
    ).toBeTruthy()
  })

  // Django's NumericPasswordValidator rejects these server-side, so the client
  // has to agree or the form would pass something the API refuses.
  it('rejects a password made only of numbers', () => {
    const message = errorFor(
      changePasswordSchema,
      { ...valid, new_password: '12345678', confirm_password: '12345678' },
      'new_password',
    )
    expect(message).toBe('Password cannot be only numbers.')
  })

  it('rejects a confirmation that does not match', () => {
    const result = changePasswordSchema.safeParse({
      ...valid,
      confirm_password: 'somethingelse',
    })
    expect(result.success).toBe(false)
  })
})
