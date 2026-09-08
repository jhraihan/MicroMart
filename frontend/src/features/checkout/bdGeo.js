/*
 * Bangladesh administrative geography for the address form (FR-CHK-2):
 * division and district are selects, everything below them is free text.
 */
export const DIVISIONS = [
  {
    name: 'Barishal',
    districts: ['Barguna', 'Barishal', 'Bhola', 'Jhalokati', 'Patuakhali', 'Pirojpur'],
  },
  {
    name: 'Chattogram',
    districts: [
      'Bandarban',
      'Brahmanbaria',
      'Chandpur',
      'Chattogram',
      'Cumilla',
      "Cox's Bazar",
      'Feni',
      'Khagrachhari',
      'Lakshmipur',
      'Noakhali',
      'Rangamati',
    ],
  },
  {
    name: 'Dhaka',
    districts: [
      'Dhaka',
      'Faridpur',
      'Gazipur',
      'Gopalganj',
      'Kishoreganj',
      'Madaripur',
      'Manikganj',
      'Munshiganj',
      'Narayanganj',
      'Narsingdi',
      'Rajbari',
      'Shariatpur',
      'Tangail',
    ],
  },
  {
    name: 'Khulna',
    districts: [
      'Bagerhat',
      'Chuadanga',
      'Jashore',
      'Jhenaidah',
      'Khulna',
      'Kushtia',
      'Magura',
      'Meherpur',
      'Narail',
      'Satkhira',
    ],
  },
  {
    name: 'Mymensingh',
    districts: ['Jamalpur', 'Mymensingh', 'Netrokona', 'Sherpur'],
  },
  {
    name: 'Rajshahi',
    districts: [
      'Bogura',
      'Chapai Nawabganj',
      'Joypurhat',
      'Naogaon',
      'Natore',
      'Pabna',
      'Rajshahi',
      'Sirajganj',
    ],
  },
  {
    name: 'Rangpur',
    districts: [
      'Dinajpur',
      'Gaibandha',
      'Kurigram',
      'Lalmonirhat',
      'Nilphamari',
      'Panchagarh',
      'Rangpur',
      'Thakurgaon',
    ],
  },
  {
    name: 'Sylhet',
    districts: ['Habiganj', 'Moulvibazar', 'Sunamganj', 'Sylhet'],
  },
]

export const DIVISION_NAMES = DIVISIONS.map((division) => division.name)

export function districtsFor(divisionName) {
  return DIVISIONS.find((division) => division.name === divisionName)?.districts ?? []
}

/** The division a district belongs to, for prefilling from a saved address. */
export function divisionForDistrict(districtName) {
  return DIVISIONS.find((division) => division.districts.includes(districtName))?.name ?? ''
}
