"""
Category tree and brand list for the demo catalogue.

Structure notes, both enforced elsewhere and worth restating here so nobody
adds a row that will not load:

* **One level of nesting.** `Category.clean()` refuses a grandchild, so a
  child's `parent` must always be a root. The tree below is therefore
  (root, [children]) and cannot grow deeper.
* **Slugs are the API contract.** `?category=<slug>` and `/c/<slug>` both
  quote them, so renaming a slug breaks saved links. Rename the display name
  freely; leave the slug alone.

Categories carry a short blurb used as the category page's meta description
and intro copy. It is original text written for this store.
"""

# (name, slug, blurb, [(child name, child slug), ...])
CATEGORY_TREE = [
    (
        "Desktop",
        "desktop",
        "Prebuilt desktops and all-in-ones, assembled and tested before they ship.",
        [
            ("Gaming PC", "gaming-pc"),
            ("All-in-One PC", "all-in-one-pc"),
            ("Office Desktop", "office-desktop"),
        ],
    ),
    (
        "Laptop",
        "laptop",
        "Portable machines for study, work and play, with official warranty.",
        [
            ("Gaming Laptop", "gaming-laptop"),
            ("Ultrabook", "ultrabook"),
            ("Business Laptop", "business-laptop"),
        ],
    ),
    (
        "Component",
        "component",
        "Everything that goes inside the case, from processors to power supplies.",
        [
            ("Processor", "processor"),
            ("CPU Cooler", "cpu-cooler"),
            ("Motherboard", "motherboard"),
            ("RAM", "ram"),
            ("Graphics Card", "graphics-card"),
            ("SSD", "ssd"),
            ("Hard Disk Drive", "hard-disk-drive"),
            ("Power Supply", "power-supply"),
            ("PC Case", "pc-case"),
        ],
    ),
    (
        "Monitor",
        "monitor",
        "Displays for gaming, design and long office days.",
        [
            ("Gaming Monitor", "gaming-monitor"),
            ("Office Monitor", "office-monitor"),
        ],
    ),
    ("UPS", "ups", "Keep your machine alive through a load-shedding cut.", []),
    ("Tablet", "tablet", "Tablets for reading, drawing and light work.", []),
    ("Mobile Phone", "mobile-phone", "Smartphones across every budget.", []),
    (
        "Camera",
        "camera",
        "Cameras for creators, from pocket action cams to full mirrorless bodies.",
        [
            ("Action Camera", "action-camera"),
            ("Mirrorless Camera", "mirrorless-camera"),
        ],
    ),
    (
        "Networking",
        "networking",
        "Routers, switches and adapters to get every room online.",
        [
            ("Router", "router"),
            ("Network Switch", "network-switch"),
            ("Network Adapter", "network-adapter"),
        ],
    ),
    (
        "Accessories",
        "accessories",
        "The parts you touch all day -- keyboards, mice, audio and more.",
        [
            ("Keyboard", "keyboard"),
            ("Mouse", "mouse"),
            ("Headphone", "headphone"),
            ("Speaker", "speaker"),
            ("Microphone", "microphone"),
            ("Webcam", "webcam"),
        ],
    ),
    (
        "Printer",
        "printer",
        "Printers and scanners for home, study and small offices.",
        [
            ("Inkjet Printer", "inkjet-printer"),
            ("Laser Printer", "laser-printer"),
        ],
    ),
    ("Projector", "projector", "Projectors for classrooms, offices and film nights.", []),
    ("TV", "tv", "Smart televisions in every size a living room needs.", []),
    ("Air Conditioner", "air-conditioner", "Inverter air conditioners built for a Dhaka summer.", []),
    (
        "Gadget",
        "gadget",
        "Smart watches, power banks and the small things that make a day easier.",
        [
            ("Smart Watch", "smart-watch"),
            ("Power Bank", "power-bank"),
        ],
    ),
    (
        "Gaming",
        "gaming",
        "Chairs, consoles and controllers for the people who play properly.",
        [
            ("Gaming Chair", "gaming-chair"),
            ("Gaming Console", "gaming-console"),
            ("Controller", "controller"),
        ],
    ),
    ("Software", "software", "Genuine licences for the software you actually need.", []),
    (
        "Server & Storage",
        "server-storage",
        "Network storage and external drives for teams and archives.",
        [
            ("NAS Storage", "nas-storage"),
            ("External Storage", "external-storage"),
        ],
    ),
]

# Brands, with the accent colour their generated placeholder artwork uses.
# The colour is ours, chosen for contrast on a light card -- it is not any
# manufacturer's brand colour, and the placeholder is deliberately a plain
# lettered tile rather than anything resembling a logo.
BRANDS = [
    ("AMD", "#7b1f2b"),
    ("Intel", "#134a7a"),
    ("NVIDIA", "#2f5d2f"),
    ("Asus", "#1f3a6e"),
    ("MSI", "#5c1f1f"),
    ("Gigabyte", "#3d3172"),
    ("Lenovo", "#7a1f2e"),
    ("HP", "#14506b"),
    ("Dell", "#15406b"),
    ("Acer", "#2b5c33"),
    ("Apple", "#3a3a3c"),
    ("Samsung", "#1f3d7a"),
    ("Xiaomi", "#8a3a12"),
    ("Realme", "#7a4a12"),
    ("Corsair", "#333a42"),
    ("Logitech", "#2b5570"),
    ("Razer", "#2c5f2c"),
    ("Kingston", "#7a2020"),
    ("Western Digital", "#1f4470"),
    ("Seagate", "#2f5a35"),
    ("TP-Link", "#1d5a6e"),
    ("Cooler Master", "#4a3f6b"),
    ("Thermaltake", "#6b2020"),
    ("BenQ", "#6b4a12"),
    ("LG", "#7a1f45"),
    ("Sony", "#2c3e50"),
    ("Canon", "#7a1f1f"),
    ("Epson", "#1f3f7a"),
    ("Brother", "#3f5a1f"),
    ("Havit", "#2f4a6b"),
    ("A4Tech", "#5a3a6b"),
    ("Walton", "#1f5a4a"),
    ("Microsoft", "#1f5a7a"),
    ("Synology", "#2b4a6b"),
    ("Anker", "#2f4f6f"),
]
