# StarTech-Style E-Commerce Design System

Reverse-engineered from **https://www.startech.com.bd/** (OpenCart "starship" theme, `home.min.31.css`, fetched 2026-08-18). All values below are the real values used by that site, reorganized into a reusable system.

---

## 1. Design Principles

| Principle | How it shows up |
|---|---|
| **Density over whitespace** | 5 product cards per row, 8 category tiles per row, 14px base text. Maximum SKUs above the fold. |
| **Two-color logic** | Orange-red = commerce/price/urgency. Indigo blue = actions/UI/navigation. Never mixed roles. |
| **Flat cards on gray** | White cards, 5px radius, 1px hairline shadow on a light gray page. Depth only on hover. |
| **Dark chrome, light content** | Near-black navy header + footer bracket a light content area. |
| **Icon-led scanning** | Material Icons everywhere: nav, category tiles, trust cards, footer buttons. |
| **Price is the hero** | Price is bolder and larger than product name. Old price struck through, savings badge on image. |

---

## 2. Color Tokens

### 2.1 Core palette (source `:root`)

```css
:root {
  --s-primary:      #ef4a23; /* orange-red — brand, links, active, price accent */
  --s-primary-dark: #d51e0b; /* deep red — price text, discount pill, pagination active */
  --s-secondary:    #3749bb; /* indigo — buttons, secondary actions, focus */
  --s-tertiary:     #838383; /* muted gray — captions on dark bg */
  --s-hf-bg:        #081621; /* header/footer background (near-black navy) */
  --s-b-bg:         #f2f4f8; /* page / block background gray */
  --s-m-bg:         #6e2594; /* purple — "mark" / save badge */
  --s-s-bg:         rgba(55,73,187,.05); /* indigo 5% — subtle button/row fill */
  --s-f-c1:         #666666; /* body secondary text */
  --s-f-c2:         #ffffff; /* text on dark */
}
```

### 2.2 Extended / derived values found in use

```css
:root {
  /* neutrals */
  --n-900: #111111;  /* primary text, headings, links-on-light */
  --n-800: #222222;  /* nav link text */
  --n-700: #333333;  /* dividers on dark */
  --n-600: #444444;
  --n-500: #666666;  /* = --s-f-c1 */
  --n-400: #888888;
  --n-300: #999999;  /* placeholder, disabled */
  --n-200: #dddddd;  /* input border */
  --n-150: #eeeeee;  /* card divider, hairline border */
  --n-100: #f1f3f5;  /* input fill, pagination fill */
  --n-075: #f2f5f9;  /* compare button fill */
  --n-050: #fafafa;  /* nested dropdown bg (mobile) */
  --white: #ffffff;

  /* accents */
  --acc-blue-deep:  #00237e; /* gradient stop */
  --acc-cyan:       #0bc1e9; /* gradient stop */
  --acc-indigo-alt: #2b398f; /* trust-card icon circle */
  --acc-amber:      #ef9919; /* "Find store" CTA */
  --acc-amber-soft: #ffe8a1; /* warning surface */
  --acc-orange:     #f58220;
  --acc-red:        #f51414; /* error text */
  --acc-red-hot:    #e5330b; /* active mobile state */
  --acc-green:      #15b579; /* in-stock / success */
  --surf-red-soft:  #fff0f0; /* deal-code strip */

  /* semantic aliases */
  --brand:        var(--s-primary);
  --price:        var(--s-primary-dark);
  --action:       var(--s-secondary);
  --page-bg:      var(--s-b-bg);
  --card-bg:      var(--white);
  --chrome-bg:    var(--s-hf-bg);
  --text:         var(--n-900);
  --text-muted:   var(--s-f-c1);
  --border:       var(--n-150);
  --success:      var(--acc-green);
  --danger:       var(--acc-red);
  --warning:      var(--acc-amber);
}
```

### 2.3 Color role rules

- **Never** use `--s-primary` for a button fill on light backgrounds; it is reserved for links, hover text, active dots, and icon glyphs. Button fill is `--s-secondary`.
- Price text is always `--s-primary-dark`. Discount pill = `--s-primary-dark` bg + white text.
- "Save X (-Y%)" badge is `--s-m-bg` purple — deliberately different from price red so both read at once.
- Any tinted row/chip fill on white uses `--s-s-bg` (indigo @ 5%), not a gray.

---

## 3. Typography

```css
:root {
  --font-sans: "Trebuchet MS", "Segoe UI", Tahoma, Verdana, sans-serif;
  --font-icon: "Material Icons";
}
body { font-family: var(--font-sans); font-size: 15px; color: var(--n-900); }
```

No webfont for text — system stack only. Icons come from Material Icons.

### 3.1 Type scale (px, as used)

| Token | Size / line-height | Weight | Use |
|---|---|---|---|
| `display` | 48 / 1.1 | bold | hero numerals, campaign |
| `h-xl` | 38 | bold | landing hero |
| `h-lg` | 30–32 | bold | page hero |
| `h-1` | 24 | bold | page title (desktop) |
| `h-2` | 20 / 26 | bold | section header (`.m-header`) |
| `h-3` | 18 / 24 | bold | card blurb, subsection |
| `h-4` | 16 / 20 | bold | block title, sidebar heading |
| `body-lg` | 15 / 22 | 400 | product name, body default |
| `price` | 17 / 22 | 600 | product price |
| `body` | 14 / 20 | 400 | UI default, nav links (600), table |
| `small` | 13 / 16 | 400/600 | spec bullets, small buttons, badges |
| `xs` | 12 / 16 | 600 | old price, footnotes, pagination |
| `micro` | 11 / 16 | 400 | header sub-labels |
| `overline` | 14, `letter-spacing: 4px`, uppercase | 400 | footer column headings |

### 3.2 Heading defaults

```css
h1,h2,h3,h4,h5,h6 { margin-top: 0; font-weight: bold; }
h1 { font-size: 20px; line-height: 28px; }
h2 { font-size: 20px; line-height: 26px; margin-bottom: 5px; }
h3 { font-size: 16px; }
h4 { font-size: 16px; line-height: 20px; margin-bottom: 5px; }
```

Mobile: `body { font-size: 14px }`, `.m-header { font-size: 18px; line-height: 20px }`.

---

## 4. Spacing, Radius, Elevation

### 4.1 Spacing scale (5px base, effectively 5 / 10 / 15 / 20 / 30 / 40 / 50)

```css
:root {
  --sp-1: 5px;  --sp-2: 10px; --sp-3: 15px;
  --sp-4: 20px; --sp-6: 30px; --sp-8: 40px; --sp-10: 50px;
}
```
Card interior padding = `--sp-3` (15px). Section padding = `--sp-3` vertical. Footer top padding = `--sp-10`.

### 4.2 Radius

```css
:root {
  --r-xs: 2px; --r-sm: 3px;  --r-md: 4px;  /* inputs, buttons */
  --r-lg: 5px;                             /* cards, panels — the default */
  --r-xl: 10px;                            /* sliders, banners */
  --r-2xl: 15px;                           /* category tiles */
  --r-pill: 20px;                          /* discount pill, chips */
  --r-round: 50px;                         /* icon circles, big CTA */
  --r-full: 50%;
}
```
Save-badge uses asymmetric `border-radius: 0 20px 20px 0` (flush to card's left edge).

### 4.3 Elevation

```css
:root {
  --el-1: 0 1px 1px rgba(0,0,0,.10);          /* card at rest */
  --el-2: 0 2px 5px rgba(0,0,0,.10);          /* card hover */
  --el-3: 0 2px 2px rgba(0,0,0,.10);          /* sticky bars */
  --el-4: 0 5px 5px rgba(0,0,0,.20);          /* mobile fixed header */
  --el-drop: 0 5px 5px rgba(0,0,0,.1), 0 10px 15px rgba(0,0,0,.1); /* dropdown */
  --el-flat: 5px 5px 0 rgba(0,0,0,.03);       /* offset flat shadow */
}
```
Dropdown adds a brand top edge via a third shadow: `0 -3px 0 0 var(--s-primary)`.

**Hover-darken trick** (used site-wide instead of a second color): `box-shadow: 0 50px rgba(0,0,0,.2) inset;` — an inset shadow taller than the element darkens the fill on hover.

### 4.4 Motion

```css
:root { --t-base: 300ms linear; --t-fast: 300ms; }
```
Buttons: `transition: all 300ms linear`. Gradient CTA: `animation: gradient 15s ease infinite` over `background-size: 400% 400%`.

---

## 5. Layout & Grid

```css
:root { --container: 1320px; --gutter: 15px; --gutter-tight: 7.5px; --sidebar: 280px; }

.container { width:100%; max-width: var(--container); margin-inline:auto; padding-inline: var(--gutter); }
.row { display:flex; flex-wrap:wrap; margin-inline: calc(var(--gutter) * -1); }
```

- 12-column flex grid (`.col-lg-3` = `flex: 0 0 25%`).
- Product grid uses a tighter gutter: `.p-items-wrap { margin: 0 -5px }`, each `.p-item { padding: 0 5px 10px }`.
- Category/product listing page: fixed left sidebar `280px` + fluid `#content` with `padding-left: 20px`.

### 5.1 Breakpoints

| Name | Query | Notes |
|---|---|---|
| `xs` | `≤410px` | smallest phone tweaks |
| `sm` | `≤480px` | 1-up product list |
| `md` | `≤767px` / `≥768px` | container 720px; mobile nav drawer |
| `lg` | `≤991px` / `≥992px` | container 960px; sidebar collapses |
| `xl` | `≤1279px` / `≥1280px` | container 100% → fixed |
| `2xl` | `≥1366px` | container 1320px |

### 5.2 Responsive column counts

| Component | ≥1280 | ≤1279 | ≤991 | ≤767 | ≤480 |
|---|---|---|---|---|---|
| Product card `.p-item` | 5 (20%) | 4 (25%) | 3 | 2 (50%) | 1 (100%) |
| Category tile `.cat-item` | 8 (12.33%) | 6 (16.66%) | 4 (25%) | 4 | 4 |

---

## 6. Components

### 6.1 Header (3 zones, dark chrome)

Structure: `header#header > .top > .container > .ht-item{logo|search|q-actions}` then a full-width nav bar.

```css
#header .top { background: var(--s-hf-bg); padding: 15px 0; }
#header .top .container { display: flex; }
.ht-item { flex: 1 1 auto; }
.ht-item.logo { flex: 0 0 160px; }
.ht-item.logo img { height: 52px; width: auto; }
.ht-item.q-actions { flex: 0 0 550px; padding: 9px 0 0 10px; }
```

**Search field** (center, fills remaining space):
```css
.search { display:flex; background:#f1f3f5; border-radius:3px; padding:1px; position:relative; }
.search input  { flex:1; height:28px; border:none; background:none; padding:0 10px; outline:none; }
.search button { line-height:30px; font-size:20px; cursor:pointer; } /* material icon */
```

**Quick actions** — icon + two-line text ("Offers / Latest Offers", "Happy Hour / Special Deals", "PC Builder", "Compare (0)", cart):
```css
.ac { float:left; display:flex; padding-left:18px; }
.ac .ic { width:32px; height:32px; margin-right:10px; display:flex; justify-content:center;
          line-height:32px; border-radius:30px; }
.ac .ic i { color: var(--s-primary); font-size:24px; line-height:36px; }
.ac h5 { margin:0; font-size:15px; font-weight:normal; }
.ac p  { margin:0; font-size:11px; line-height:16px; color: var(--s-tertiary); white-space:nowrap; }
```

**Cart summary box**:
```css
.cart-info { flex:0 0 180px; padding:10px 15px; border:1px solid #eee; border-radius:5px;
             display:flex; flex-direction:column; }
.cart-info > span { display:flex; justify-content:space-between; padding-bottom:5px;
                    font-size:14px; line-height:20px; color:#888; }
.cart-info > span > span { font-weight:bold; color:#111; font-size:15px; }
.cart-info .cart-quantity { border-bottom:1px solid #eee; margin-bottom:5px; }
```

**Mobile**: logo bar becomes `position: fixed; top:0; background: var(--s-hf-bg); box-shadow: var(--el-4)`, logo height 40px, body gets `padding-top: 50px`. Hamburger = three `<span>` bars.

### 6.2 Mega navigation

```css
.nav-link { display:block; padding:0 7px; line-height:50px; font-size:14px; font-weight:600;
            color:#222; white-space:nowrap; }
.nav-item:hover > .nav-link { color: var(--s-primary); }

.nav-item .drop-down {
  display:none; position:absolute; left:10px; z-index:99; background:#fff; padding:5px 0;
  box-shadow: 0 5px 5px rgba(0,0,0,.1), 0 10px 15px rgba(0,0,0,.1), 0 -3px 0 0 var(--s-primary);
}
.nav-item:hover > .drop-down { display:block; }
.nav-item:hover > .drop-menu-2 { left:100%; top:-5px; box-shadow: 0 5px 5px rgba(0,0,0,.1), 0 5px 15px rgba(0,0,0,.2); }
.multi-col > .drop-down { width:400px; }
.multi-col .drop-down > ul { display:inline-block; float:left; position:relative; }
```
- Level 1: 15 top categories. Level 2: `.drop-menu-1`. Level 3 (brands): `.drop-menu-2` flies out right.
- `.multi-col` splits a long level-2 list into columns in a 400px panel.
- `.see-all { padding-left:40px; color:#666 }` closes each column.
- `.nav-item.has-child:before` draws a 15px chevron tick (rotated 90° on mobile accordion).
- Mobile: dropdowns become static accordions (`background:#fafafa`, `.nav-item.open > .drop-down { display:block }`), `.nav-link { line-height:44px; font-size:16px; font-weight:400; padding:0 20px; border-bottom:1px solid #eee }`.

### 6.3 Product card — the primary unit

```html
<div class="p-item">
  <div class="p-item-inner">
    <div class="marks"><span class="mark">Save: 425৳ (-10%)</span></div>
    <div class="p-item-img"><a href="…"><img src="…-200x200.webp" width="228" height="228" alt="…"></a></div>
    <div class="p-item-details">
      <h4 class="p-item-name"><a href="…">Omron HEM-7121J Digital Blood Pressure Monitor</a></h4>
      <div class="p-item-price">
        <span class="price-new">3,750৳</span> <span class="price-old">4,175৳</span>
      </div>
    </div>
  </div>
</div>
```

```css
.p-items-wrap { display:flex; flex-wrap:wrap; margin:0 -5px; padding:0; justify-content:flex-start; }
.p-item { flex:0 0 20%; max-width:20%; padding:0 5px 10px; display:flex; position:relative; }

.p-item-inner { display:flex; flex-direction:column; width:100%; position:relative;
  background:#fff; border-radius:5px; box-shadow: 0 1px 1px rgba(0,0,0,.1); }
.p-item-inner:hover { box-shadow: 0 2px 5px rgba(0,0,0,.1); }

.p-item-img { flex:0 0 220px; padding:20px; margin:0; text-align:center;
  border-bottom: 3px solid rgba(55,73,187,.03); }
.p-item-img > a { height:228px; }
.p-item-img img { max-width:100%; }
.p-item-img img:hover { opacity:.9; }

.p-item-details { padding:15px; flex:1 1 auto; display:flex; flex-direction:column; }
.p-item-name { margin:0 0 15px; font-size:15px; font-weight:400; line-height:20px; overflow:hidden; }
.p-item-name a { color:#111; }
.p-item-name:hover a { color: var(--s-primary); }

.p-item-price { font-size:17px; font-weight:600; line-height:22px; color: var(--s-primary-dark); }
.p-item-price .price-old { padding-left:5px; font-size:12px; font-weight:600;
  text-decoration: line-through; color: var(--s-f-c1); }
.p-item-price .discount { margin-left:5px; padding:4px 10px; border-radius:20px;
  background: var(--s-primary-dark); color:#fff; font-size:13px; font-weight:400; }
```

**Save badge** — flag flush to the card's left edge:
```css
.marks { position:absolute; top:15px; left:0; z-index:10; display:flex; flex-direction:column; align-items:flex-start; }
.marks .mark { background: var(--s-m-bg); color:#fff; font-size:12px; line-height:14px;
  padding:3px 10px; margin-bottom:2px; border-radius: 0 20px 20px 0; flex:0 0 auto; }
```

**List/grid variant on category pages** (`.p-item-page`): 4-up, adds spec bullets + action row.
```css
.p-item-page .p-item { flex:25%; max-width:25%; }
.p-item-page .p-item .short-description { padding:10px 0 0 14px; flex:1 1 auto;
  border-bottom:1px solid #eee; margin-bottom:5px; }
.p-item-page .short-description li { font-size:13px; line-height:16px; color:#666; padding-bottom:10px; }
.p-item-page .p-item .actions { display:flex; margin:0 0 5px; }
.p-item-page .p-item .actions .st-btn { padding:0 12px; }
.p-item-page .p-item .actions .st-btn.btn-compare { background:#f2f5f9; margin-left:10px; }
```

**Coupon/deal variant**: `.p-item .deal-code { background:#FFF0F0; text-align:center }` with `p { color: var(--s-primary-dark); padding:5px 0 }`.

### 6.4 Category tile

```html
<div class="cat-item">
  <a href="/air-conditioner" class="cat-item-inner">
    <span class="cat-icon"><img src="…ac-48x48.png" width="48" height="48" alt="AC Icon"></span>
    <p>AC</p>
  </a>
</div>
```
```css
.cat-items-wrap { display:flex; flex-wrap:wrap; margin:0 -5px; }
.cat-item { flex:0 0 12.33%; padding:0 5px; margin-bottom:20px; text-align:center; }
.cat-item .cat-item-inner { display:block; background:#fff; border-radius:15px;
  padding:15px 0; box-shadow: 0 1px 1px rgba(0,0,0,.1); }
.cat-item .cat-item-inner:hover { box-shadow: 0 2px 5px rgba(0,0,0,.1); }
.cat-item .cat-icon { display:inline-block; padding:15px; }
.cat-item p { margin:0; font-size:13px; font-weight:bold; }
.cat-item:hover p { color: var(--s-primary); }
```
Mobile ≤767: 4-up, `border-radius:10px`, icon 60×60, `p { font-weight:normal; line-height:12px; min-height:25px }`.

### 6.5 Buttons

```css
/* Primary — indigo solid */
.btn {
  display:inline-block; height:42px; line-height:38px; padding:0 20px;
  background: var(--s-secondary); border:2px solid var(--s-secondary); color:#fff;
  font-size:14px; font-weight:600; text-align:center; border-radius:4px;
  cursor:pointer; outline:none; transition: all 300ms linear;
}
.btn:hover { box-shadow: 0 50px rgba(0,0,0,.2) inset; color:#fff; text-decoration:none; }

/* Tonal gray */
.btn-gray { background: var(--s-s-bg); border-color: var(--s-b-bg); color: var(--s-secondary); }
.btn-gray:hover { background: var(--s-secondary); color:#fff; }

/* Outline */
.btn-outline { display:flex; align-items:center; gap:8px;
  background:transparent; border:2px solid var(--s-secondary); color: var(--s-secondary); }
.btn-outline:hover { background: var(--s-secondary); color:#fff; }

/* Small utility button (card actions) */
.st-btn { display:flex; justify-content:center; line-height:34px; padding:0 14px;
  background: var(--s-s-bg); color: var(--s-secondary);
  border-radius:4px; font-size:13px; font-weight:600; text-decoration:none; cursor:pointer; }
.st-btn:hover { background: var(--s-secondary); color:#fff; }

/* Ghost compare link */
.btn-compare { background:none; border:none; margin-top:7px;
  color:#666; font-size:13px; font-weight:400; text-decoration:none; }
.btn-compare:hover { background:#f1f3f5; color:#111; }

/* Disabled / stock state */
.stock-status { cursor:default; opacity:.7;
  background: rgba(55,75,185,.1) !important; color: var(--s-secondary) !important; }

/* Feature CTA — animated gradient (PC Builder) */
.build-pc .btn { border:none; line-height:42px;
  background: linear-gradient(45deg,#00237e,#3749bb,#0bc1e9,#3749bb,#00237e);
  background-size:400% 400%; animation: gradient 15s ease infinite; }

/* Amber pill CTA (store finder) */
.btn.find { background:#EF9919; color: var(--s-hf-bg); border:none;
  padding:17px 50px; border-radius:50px; font-size:15px; line-height:20px; height:auto;
  width:fit-content; margin-left:auto; }
.btn.find:hover { box-shadow: 0 60px rgba(0,0,0,.2) inset; }

/* Icon + label */
.btn.buy-now { display:flex; align-items:center; gap:8px; }
```

Sizes: **lg** = the amber pill (~54px), **md** = 42px (`.btn`, default), **sm** = 34px (`.st-btn`), **xs** = 28–30px (inline search).
Mobile: `.btn { width:100%; text-align:center; margin-top:10px }`.

### 6.6 Form controls

```css
input, select, textarea {
  width:100%; height:42px; padding:5px 15px; font-size:15px;
  font-family: var(--font-sans); background:#fff;
  border:1px solid #ddd; border-radius:4px; outline:none;
}
```
Inline/filled variant (search, coupon): `background:#f1f3f5; border:none; height:28–36px; border-radius:3px`.

### 6.7 Trust / info card

```html
<div class="c-card">
  <div class="ic"><i class="material-icons">store</i></div>
  <div><span class="label">Stores</span><div class="blurb">20+ Physical Stores</div></div>
</div>
```
```css
.c-card { display:flex; align-items:center; padding:15px 20px; }
.c-card .ic { width:50px; height:50px; line-height:50px; margin-right:20px;
  background:#2B398F; border-radius:50px; text-align:center; }
.c-card .ic .material-icons { line-height:50px; color:#fff; }
.c-card .label { display:block; color:#666; line-height:26px; }
.c-card .blurb { color:#000; font-size:18px; line-height:24px; font-weight:bold; }
.c-card p { color:#444; margin:0; }
```
Mobile: icon circle → `var(--s-primary)`, 35px, blurb 13–14px, padding 8–10px.

### 6.8 White surface / panel

```css
.ws-box  { background:#fff; border-radius:5px; box-shadow: 0 1px 1px rgba(0,0,0,.1); }
.g-box   { background: var(--s-b-bg); border-radius:5px; padding:20px; }
.bg-gray { background: var(--s-b-bg); }
.bg-bt-gray { background: var(--s-b-bg); border-top:1px solid #ddd; }
```

### 6.9 Section header

```css
.m-header { text-align:center; font-size:20px; line-height:26px; font-weight:bold; }
.m-header button { float:right; }
```
Pattern: `<h2 class="m-header">Featured Category</h2>` centered, optional right-floated "View All" button. Mobile: 18px/20px.

### 6.10 Hero slider

```css
.home-slider { position:relative; }
.home-slider img { width:100%; border-radius:10px; }
.home-slider .slider-dot { position:absolute; inset:auto 0 0 0; padding:10px 0; text-align:center; }
.home-slider .slider-dot .dot { display:inline-block; width:30px; height:8px; margin:0 5px;
  background:#fff; opacity:.5; cursor:pointer; }
.home-slider .slider-dot .dot.active { background: var(--s-primary); opacity:1; }
```
Dots are **bars**, not circles — 30×8, active turns brand orange.

### 6.11 Live search results dropdown

```css
.search-results { padding:10px; height:450px; overflow:auto; }
.search-item { border-radius:5px; }
.search-item:hover { background: rgba(55,73,187,.04); }
.search-item a { display:inline-block; width:100%; padding:10px 20px; text-decoration:none; }
.search-item a .image { float:left; width:60px; height:60px; padding:8px; }
.search-item a .name  { margin-left:80px; padding:10px 0 6px; color:#111; }
.search-item a .price { margin-left:80px; font-size:16px; font-weight:bold; }
.search-item.empty { border:none; text-align:center; padding:100px 0 0; color:#999; }
.search-item.remainder-count a { text-align:center; line-height:20px;
  background: rgba(240,75,35,.02); border-radius:5px; }
.search-item.remainder-count a:hover { background: rgba(240,75,35,1); color:#fff; }
```

### 6.12 Breadcrumb

```css
.breadcrumb { display:block; margin-bottom:15px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.breadcrumb li { display:inline; font-size:14px; line-height:16px; color:#666; }
.breadcrumb li:before { content:"/"; margin:0 5px; }
.breadcrumb li:first-child:before { content:""; display:none; }
.breadcrumb li a { color:#111; }
.breadcrumb li:last-child a { color:#666; }
.breadcrumb li a i { float:left; font-size:16px; color:#666; } /* home icon */
```

### 6.13 Pagination

```css
.pagination li { display:inline-block; min-width:36px; margin:0 5px 5px 0;
  font-size:12px; font-weight:bold; line-height:34px; text-align:center;
  transition: background-color .3s; }
.pagination li span { display:block; padding:0 10px; background:#f1f3f5; color:#111; border-radius:4px; }
.pagination li span.disabled { color:#666; cursor:default; }
.pagination li.active span { background-color: var(--s-primary-dark); color:#fff; }
.pagination li:hover a { background-color: var(--s-primary-dark); color:#fff; font-weight:bold; }
```

### 6.14 Listing toolbar

```css
.top-bar { padding:10px 10px 10px 20px; margin-bottom:10px; }
.top-bar .page-heading { font-size:16px; line-height:30px; font-weight:bold; }
.top-bar .show-sort { text-align:right; }
.bottom-bar { padding:15px 0; margin:15px 0; min-height:36px;
  border-top:1px solid #eee; border-bottom:1px solid #eee; }
.nav-tabs { background: rgba(55,73,187,.05); padding:0 20px 10px; }
.nav-tabs li { line-height:30px; }
```

### 6.15 Cart drawer

```css
.footer { flex:0 0 auto; padding:5px 0 43px; position:relative; }
.footer .total { display:flex; padding:12px 10px; }
.footer .total > div { flex:1 1 50%; text-align:right; font-size:16px; color:#666; }
.footer .total > div.amount { color:#111; font-weight:600; }
.footer .promotion-code { background: var(--s-s-bg); padding:10px; width:100%; display:inline-block; }
.footer .promotion-code input,
.footer .promotion-code button { height:36px; font-size:14px; border:none; }
.footer .checkout-btn { position:absolute; inset:auto 0 0 0; }
.footer .checkout-btn a button { width:100%; background: var(--s-primary); border:none; border-radius:0; }
```
Note: the sticky checkout button is the one place `--s-primary` is used as a button fill — full-bleed, square corners.

### 6.16 Footer

```css
footer { background: var(--s-hf-bg); padding:50px 0 0; position:relative; }
footer .container { display:flex; padding-bottom:30px; border-bottom:1px solid rgba(255,255,255,.1); }
footer .org-info   { flex:1 1 25%; padding-left:50px; }
footer .about-us   { flex:1 1 50%; }
footer .contact-us { flex:1 1 25%; padding-right:50px; }

footer h4 { margin-bottom:30px; color: var(--s-f-c2);
  font-size:14px; font-weight:normal; text-transform:uppercase; letter-spacing:4px; }
footer .org-info p { color: var(--s-tertiary); font-size:14px; }
footer .org-info p b.store-name { color: var(--s-f-c2); font-weight:normal; }

.footer-big-btn { display:block; padding:10px 0; margin-bottom:20px;
  border:1px solid rgba(255,255,255,.1); border-radius:50px; cursor:pointer; }
.footer-big-btn:hover { box-shadow: 0 -70px 0 rgba(0,0,0,.2) inset;
  border-color: var(--s-primary); text-decoration:none; }
.footer-big-btn .ic { float:left; padding:0 10px 0 20px; margin-right:20px;
  font-size:36px; line-height:40px; color: var(--s-f-c2); border-right:1px solid #333; }
.footer-big-btn h5 { margin:0; color: var(--s-primary); font-size:20px; line-height:28px; font-weight:normal; }
.footer-big-btn p  { margin:0 0 4px; color: var(--s-tertiary); font-size:12px; line-height:16px; }

.social-links { padding:0; margin:0; text-align:right; }
.social-links a { display:inline-block; width:40px; height:40px; padding:8px; margin-left:6px;
  border-radius:40px; text-align:center; font-size:24px; background: rgba(255,255,255,.1); }
.social-links a:hover { background: var(--s-secondary); }

.sub-footer { padding:15px 0 25px; background: rgba(0,0,0,.4); }
.sub-footer p { margin:0; font-size:12px; color: var(--s-tertiary); }
.sub-footer .powered-by { text-align:right; }
```
Mobile: `.footer-big-btn { max-width:300px; margin:0 auto 20px }`, social + powered-by center.

### 6.17 Icons

Material Icons ligature font (`<i class="material-icons">search</i>`), 20 / 24 / 32 / 36 / 48px. Glyphs in use: `search`, `shopping_basket`, `card_giftcard`, `flash_on` (with `.blink` animation), `important_devices`, `library_add`, `store`.
Social icons use a sprite: `.icon-sprite { width:24px; height:24px; background:url(icon-sprite-v8.png) no-repeat }` with `background-position` offsets per network (`-72px 0` youtube, `-96px 0` insta, `-168px 0` whatsapp).

---

## 7. Patterns

### 7.1 Homepage composition (top → bottom)
1. Dark header (logo / search / quick actions / cart)
2. Sticky mega-nav (15 categories)
3. Hero slider (10px radius) + side banners
4. `c-card` trust strip (stores, delivery, support, warranty)
5. **Featured Category** — 8-up `cat-item` tiles
6. **Featured Products** — 5-up `p-item` cards
7. Repeated brand/category product rows with "View All"
8. SEO copy blocks (`<h2>Best Laptop Shop in Bangladesh</h2>` + prose)
9. App download + store-finder CTA
10. Dark footer, 3 columns + social, then `sub-footer`

### 7.2 Price display rules
- Discounted: `price-new` (17px/600, `--s-primary-dark`) + `price-old` (12px, struck, `#666`) + optional `.discount` pill.
- Full price: `price-new` only.
- Currency `৳` follows the number with no space: `3,750৳`. Thousands separated by comma.
- Savings shown as absolute + percent on the image badge: `Save: 425৳ (-10%)`.

### 7.3 Card hover contract
Shadow `--el-1` → `--el-2`, image `opacity: .9`, name color → `--s-primary`. No transform, no scale.

### 7.4 Image contract
Product thumb: 200×200 source rendered in a 228×228 box, `.webp`, explicit `width`/`height` attributes to prevent CLS. Category icon: 48×48 PNG.

---

## 8. Accessibility Notes (gaps to fix in a rebuild)

| Issue in source | Fix in your system |
|---|---|
| `--s-primary` `#ef4a23` on white = **3.1:1** — fails AA for body text | use `--s-primary-dark` `#d51e0b` (4.8:1) for text; keep `#ef4a23` for ≥18px bold or non-text |
| `--s-tertiary` `#838383` on white = 3.0:1 | only use on the dark `--s-hf-bg` (where it passes) |
| No visible `:focus-visible` styles (`outline:none` everywhere) | add `outline: 2px solid var(--s-secondary); outline-offset: 2px` |
| Hover-only mega-menu | add keyboard/`:focus-within` open, `aria-expanded`, Esc to close |
| Icon-only buttons (search, cart) | add `aria-label` |
| `.blink` animation on Happy Hour | wrap in `@media (prefers-reduced-motion: no-preference)` |
| Body 14px on mobile | keep ≥14px; ensure 16px on inputs to stop iOS zoom |

---

## 9. Starter Token File

```css
:root {
  /* brand */
  --s-primary:#ef4a23; --s-primary-dark:#d51e0b; --s-secondary:#3749bb;
  --s-tertiary:#838383; --s-hf-bg:#081621; --s-b-bg:#f2f4f8; --s-m-bg:#6e2594;
  --s-s-bg:rgba(55,73,187,.05); --s-f-c1:#666; --s-f-c2:#fff;

  /* neutral */
  --n-900:#111; --n-800:#222; --n-500:#666; --n-300:#999;
  --n-200:#ddd; --n-150:#eee; --n-100:#f1f3f5; --white:#fff;

  /* status */
  --success:#15b579; --danger:#f51414; --warning:#ef9919;

  /* type */
  --font-sans:"Trebuchet MS","Segoe UI",Tahoma,Verdana,sans-serif;
  --fs-xs:12px; --fs-sm:13px; --fs-base:14px; --fs-md:15px;
  --fs-price:17px; --fs-lg:18px; --fs-xl:20px; --fs-2xl:24px;

  /* space */
  --sp-1:5px; --sp-2:10px; --sp-3:15px; --sp-4:20px; --sp-6:30px; --sp-8:40px; --sp-10:50px;

  /* radius */
  --r-sm:3px; --r-md:4px; --r-lg:5px; --r-xl:10px; --r-2xl:15px; --r-pill:20px; --r-round:50px;

  /* elevation */
  --el-1:0 1px 1px rgba(0,0,0,.1);
  --el-2:0 2px 5px rgba(0,0,0,.1);
  --el-drop:0 5px 5px rgba(0,0,0,.1),0 10px 15px rgba(0,0,0,.1);

  /* layout */
  --container:1320px; --gutter:15px; --sidebar:280px;

  /* motion */
  --t-base:300ms linear;
}

*,::before,::after { box-sizing:border-box; }
body { margin:0; font-family:var(--font-sans); font-size:var(--fs-md);
       color:var(--n-900); background:var(--s-b-bg); }
a { color:var(--s-primary); text-decoration:none; }
a:hover { color:var(--s-primary); }
```

---

## 10. Quick Reference Card

| Need | Value |
|---|---|
| Page background | `#f2f4f8` |
| Card | `#fff`, `radius 5px`, `shadow 0 1px 1px rgba(0,0,0,.1)`, `padding 15px` |
| Card hover | `shadow 0 2px 5px rgba(0,0,0,.1)` |
| Primary button | `#3749bb` fill, `2px` same-color border, `42px` tall, `radius 4px`, `14px/600` |
| Button hover | `box-shadow: 0 50px rgba(0,0,0,.2) inset` |
| Price | `17px/600`, `#d51e0b` |
| Old price | `12px/600`, `#666`, line-through |
| Body text | `14–15px`, `#111`; secondary `#666` |
| Link | `#ef4a23` |
| Header/footer | `#081621` |
| Container | `1320px`, `15px` gutter |
| Product grid | 5 / 4 / 3 / 2 / 1 across breakpoints, `5px` half-gutter |
| Hairline | `1px solid #eee` |
| Input | `42px`, `1px #ddd`, `radius 4px`, `padding 5px 15px` |
