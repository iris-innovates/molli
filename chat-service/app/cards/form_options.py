"""Static option vocabularies for the IT issue intake dialog.

Single source of truth for the selection lists used by the dialog builder
in app/cards/dialog.py. Keeping these here (rather than inline in the
builder) means the vocabularies can be maintained in one place as the
Freshservice admin confirms the canonical values.

NOTE on selection pre-fill: when Molli pre-fills a selection field, the
value it supplies must match one of these strings EXACTLY (character for
character) or nothing gets selected and it fails silently. If/when an LLM
infers these from chat, constrain it to pick from these lists or fuzzy-match
its guess back onto an exact value before building the dialog.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Affected Location (MULTI_SELECT)
# Source: Freshservice location field, June 2026.
# ---------------------------------------------------------------------------
LOCATIONS: list[str] = [
    "1820 at Centennial",
    "21 Pearl",
    "24 Longview",
    "2909 Oliver",
    "61 Vandy",
    "Auraria Lofts",
    "Axis West Campus",
    "Blue Hill",
    "Cabana Beach Gainesville",
    "Cabana Beach San Marcos",
    "Campus Edge",
    "Colonial Village",
    "Corporate: Accounting",
    "Corporate: Construction Mgmt",
    "Corporate: Executive Team",
    "Corporate: HR",
    "Corporate: IT",
    "Corporate: Management Specialists",
    "Corporate: Marketing",
    "Corporate: New Business",
    "Corporate: Operations",
    "Corporate: PM",
    "Courtyard Lofts",
    "Crossing Place",
    "Eastern on 10th",
    "Flats at Carrs Hill",
    "Gamecock Village",
    "Garnet Crossing",
    "Gateway at Huntsville",
    "Gorman Row",
    "Greene Crossing",
    "Greene Crossing - Commercial",
    "High View",
    "Hoffler Place",
    "Hoffler Place - Commercial",
    "Holleman Crossing",
    "IRIS",
    "Logan Square",
    "Madera",
    "Method Townhomes",
    "Midtown Auburn",
    "Midtown Auburn - Commercial",
    "Mustang Village",
    "Nova Knoxville",
    "Nova Knoxville - Commercial",
    "Orion on Orpington",
    "Platos Lofts at Randall",
    "Preiss Residential Living",
    "Proximity at 10th",
    "Quantum on West Call",
    "Raleigh Condos",
    "Redfield Villages",
    "Red Wolf Crossing",
    "River Club Apartments",
    "Riverfront Village",
    "Signature 1505",
    "Signature 1909",
    "Signature at Varsity",
    "Signature Hartwell Village",
    "Signature Music Row",
    "Signature Music Row - Commercial",
    "Signature on Grand",
    "Social Block",
    "Tenzing Portfolio",
    "The Avenue at Norman",
    "The Boundary at West End",
    "The Bridges Dinkytown",
    "The Collective at Auburn",
    "The Collective at Clemson",
    "The Collective at Kennesaw",
    "The Collective at Lawrence",
    "The Collective at Lubbock",
    "The Collective at Norman",
    "The Edition on Oberlin",
    "The Edition on Rosemary",
    "The Forum at Sam Houston",
    "The Gathering at UC",
    "The Greens at Tryon",
    "The Knoll Dinkytown",
    "The Lookout",
    "The Mill",
    "The Nest at 4955",
    "The Nest at University Center",
    "The One Clemson",
    "The Outpost",
    "The Park on Morton",
    "The Park on Morton - Commercial",
    "The Province Greensboro",
    "The Row (Columbia, MO)",
    "The Row at the Stadium",
    "The Townhomes at River Club",
    "The Union",
    "The Vine at Bermuda Run",
    "The Warehouse",
    "The Wynwood",
    "University Trails",
    "University Village at Clemson (UV)",
    "University Woods",
    "Valentine Commons",
    "Valentine Commons - Commercial",
    "Venue on Guadalupe",
    "Venue on Guadalupe - Commercial",
    "View at Legacy Oaks",
    "Villas on Guadalupe",
    "Villas on Guadalupe - Commercial",
    "Vintages at Clemson",
]

# ---------------------------------------------------------------------------
# System Item (DROPDOWN)
# Source: Freshservice system item field, June 2026.
# Placeholder entry "..." and "Other - do not use" intentionally omitted.
# ---------------------------------------------------------------------------
SYSTEM_ITEMS: list[str] = [
    "Computer/Laptop",
    "Daily Number (DN) Spreadsheet",
    "Entrata",
    "Google Apps (Gmail/email / Drive / Calendar / Docs)",
    "IRIS Technologies: Project Request",
    "Realpage - Knock",
    "Realpage - On-Site Online Leasing",
    "Realpage - Onesite, Financial Suite, Unified",
    "Preiss IQ / Domo",
    "Printer/Copier",
    "Turn - Workbook, Spreadsheets, Jotforms, Documents, etc",
    "Windows",
    "Adobe Products",
    "Amazon Business Account",
    "Amber",
    "Amex/Reconciliation (American Express)",
    "Appfolio",
    "Atmosphere TV",
    "Bloomberg",
    "Bonus Portal",
    "Canva",
    "CollegeHouse",
    "Community Rewards",
    "Corporate Server (TPCO CITRIX + Remanage)",
    "Courtesy Connection",
    "Email Distribution Lists",
    "Flex",
    "Document or Tutorial Request",
    "Entrata - Utilities (Edition on Oberlin)",
    "Epitiro",
    "EZ Turn",
    "GeoKey (Smart Locks)",
    "Google Chrome",
    "Google Sheets/Excel - RO, Electric, Bonus Form, Budget, Master Dashboard, etc.",
    "Grace Hill PerformanceHQ",
    "Grata (Smart Locks)",
    "HelloSign/DocuSign/Adobe Sign",
    "Homebase (Smart Locks)",
    "Hyly - Email Blasts & Drip Campaigns",
    "ILS - Apartments.com, Rent.com, etc",
    "Insurance - DPPSCIC / Stern / ePremium",
    "Leap",
    "Loaner Request/Checkout (laptops, hotspots, etc)",
    "Lock Systems",
    "Maintenance Supply Companies (HD, Lowes, Ferguson, Chadwell)",
    "MailChimp/iContact",
    "Microsoft Office",
    "Mood Media - Music",
    "National Credit Systems (NCS) - Collections",
    "Nationwide Eviction",
    "Network/Internet",
    "Notifii Packages",
    "Staples (Office Supplies)",
    "Package Lockers - Luxer One, Parcel Pending, Amazon Hub",
    "Paylease/Zego",
    "PayReady Collections",
    "Phone",
    "Property Website",
    "QR Codes",
    "Quickbooks",
    "Quote Request - Hardware/Devices or Software",
    "RentPlus/Homebody Rent Reporting",
    "Reviews/Reputation/Surveys - Opiniion, J Turner, Yelp, Google Business",
    "SmartRent (Smart Locks)",
    "Social Media - Facebook, Instagram, Google Business",
    "Stratis (Smart Locks)",
    "Student.com",
    "Tawk.to",
    "Tour24",
    "Travtus",
    "UHomes",
    "Update Office Hours",
    "Utilities - SimpleBills, Conservice, AUM",
    "Yet Another Mail Merge (YAMM)",
    "Zoom Conferencing",
]

# ---------------------------------------------------------------------------
# Group (DROPDOWN) — maps to Freshservice group_id on ticket creation.
# Source: Freshservice groups, June 2026.
#
# Unlike the other lists, group has distinct display text and submitted
# value: `name` is shown to the user, `id` is the Freshservice group_id
# sent on ticket creation. Build selection items as:
#   [{"text": g["name"], "value": str(g["id"])} for g in GROUPS]
# (value stringified — selectionInput values are strings; cast back to int
# when building the Freshservice payload.)
#
# Note: "IRIS " has a trailing space in the source data, preserved exactly
# in case the value is matched verbatim downstream.
# ---------------------------------------------------------------------------
GROUPS: list[dict[str, object]] = [
    {"id": 5000337271, "name": "IRIS "},
    {"id": 5000233136, "name": "IT"},
    {"id": 5000334601, "name": "IT + Marketing"},
    {"id": 5000263627, "name": "IT + Ops"},
    {"id": 5000340456, "name": "Kasey"},
    {"id": 5000333962, "name": "Marketing"},
    {"id": 5000333963, "name": "Mktg + Ops"},
    {"id": 5000233137, "name": "Operations"},
    {"id": 5000338615, "name": "Operations (Access)"},
    {"id": 5000338084, "name": "Ops + Mktg + IT"},
    {"id": 5000340154, "name": "Ops + Mktg + IT + BI"},
    {"id": 5000339761, "name": "OPS + Preiss IQ"},
    {"id": 5000339544, "name": "Preiss IQ"},
]

# Group is no longer shown to the user in the ticket dialog — every ticket
# still needs a group_id, so the backend sets it: Molli's inferred guess
# (analysis_to_draft_fields / RequestSpec.group_id) wins when present,
# otherwise this catch-all group is used.
FALLBACK_GROUP: dict[str, object] = {"id": 5000340154, "name": "Ops + Mktg + IT + BI"}

STATUSES: list[dict[str, object]] = [
    {"value": 2, "name": "Open"},
    {"value": 3, "name": "Pending"},
    {"value": 4, "name": "Resolved"},
    {"value": 5, "name": "Closed"},
]

# ---------------------------------------------------------------------------
# Priority — maps to Freshservice ticket `priority` on creation.
# Source: Freshservice standard priority enum.
# Display text shown to user; integer `value` sent to the API.
# ---------------------------------------------------------------------------
PRIORITIES: list[dict[str, object]] = [
    {"value": 1, "name": "Low"},
    {"value": 2, "name": "Medium"},
    {"value": 3, "name": "High"},
    {"value": 4, "name": "Urgent"},
]

# ---------------------------------------------------------------------------
# Issue / "More Detail" (level-2 of the `original_system` nested field).
# Source: Freshservice ticket_fields dump, field id 5000245243 (nested_field).
#   level 1 = original_system (System/Item)  -> keys below
#   level 2 = original_more_detail ("Issue")  -> value lists below
#   level 3 = original_issue_part_2           -> intentionally ignored
# HTML entities decoded (&amp; -> &) to match SYSTEM_ITEMS / what FS accepts.
# NOTE: systems mapping to [] have no level-2 values in Freshservice; the
#   More Detail dropdown will be empty for them. original_more_detail is a
#   required str on MolliCustomFields, so callers must supply a default
#   (e.g. "Other") for systems with an empty options list.
# ---------------------------------------------------------------------------
MORE_DETAIL_BY_SYSTEM: dict[str, list[str]] = {
    "Computer/Laptop": [
        "Not Turning On",
        "Blue Screen of Death",
        "Frozen/ Software Not Working",
        "Mouse/ Keyboard Not Working",
        "Quote for New/Replacement Computer(s)",
        "Loaner Request/Checkout",
        "Other",
    ],
    "Daily Number (DN) Spreadsheet": [
        "Blank rows on report (DN tab)",
        "Incorrect Prelease Numbers",
        "Update Goals",
        "Update Agent Counts",
        "Update Locked Agent Name",
        "Other issue",
    ],
    "Entrata": [
        "User Access & Permissions",
        "System is Down",
        "BUA",
        "DocScan (Check & Invoice Scanning)",
        "Group (Master) Lease",
        "Homebody Credit Reporting (RentPlus)",
        "Homebody Insurance",
        "ILS - Apartments.com, Rent.com, etc",
        "Import Charges",
        "Lease Docs & Fees",
        "Ledgers (Payments, Charges & Credits)",
        "Reports",
        "Resident Portal",
        "Revenue Management (Conventional)",
        "Screening Issues",
        "System Settings",
        "Training Request",
        "Something Else",
    ],
    "Google Apps (Gmail/email / Drive / Calendar / Docs)": [
        "User account issue",
        "Password Issues",
        "Add/remove user on distribution list",
        "Forward former employee emails",
        "Not Receiving Emails",
        "Mail Merge Issues",
        "Mimecast",
    ],
    "IRIS Technologies: Project Request": [],
    "Realpage - Knock": [
        "Knock not loading",
        "User account issue - add/remove user, password issues",
        "Add/remove property access",
        "Something is not working",
        "Add/remove sources/tracking info",
        "Update office hours",
        "Setting needs changed",
        "Need guidance (how to's) or other support",
    ],
    "Realpage - On-Site Online Leasing": [
        "Whoops message / System is unable to send leases",
        "On-Site not loading",
        "User account issue - add/remove user, password issues",
        "Add/remove property access",
        "Change user permissions (including countersigning)",
        "Sync Issues (with OneSite)",
        "Screening issue",
        "Update fees, charges, or documents",
        "Update Floorplans",
        "Refund app fee (Realpage Payments)",
        "Paylease (Appfolio only) refund, issue, or question",
        "SSN request (last 4 digits)",
        "Need guidance (how to's) or other support",
    ],
    "Realpage - Onesite, Financial Suite, Unified": [
        "Unified Login is not loading",
        "Add/remove user to product(s)",
        "Password issues",
        "Add/remove property access to product(s)",
        "Change user permissions on product(s)",
    ],
    "Preiss IQ / Domo": [
        "Access Issues/Requests",
        "Mini DN Issues",
        "Data Questions/Issues",
        "Other Support",
    ],
    "Printer/Copier": [
        "Computer will not connect to printer",
        "Scan to Email not working",
        "Other",
        "Toner Request",
    ],
    "Turn - Workbook, Spreadsheets, Jotforms, Documents, etc": [],
    "Windows": [
        "Windows having issues",
        "Blue Screen of Death",
        "Other",
    ],
    "...": [],
    "Adobe Products": [
        "Adobe Reader Not Working",
        "Order a Subscription",
        "Other",
    ],
    "Amazon Business Account": [],
    "Amber": [],
    "Amex/Reconciliation (American Express)": [
        "Java Update or Cannot Access Website",
        "Add a Site/Employee - please email corpap@tpco.com",
        "New Card - please email corpap@tpco.com",
        "Add GL Accounts - please email corpap@tpco.com",
    ],
    "Appfolio": [
        "Need User Account Created",
        "Need Property Access Added",
        "Something is not working",
        "Import Charges",
    ],
    "Atmosphere TV": [],
    "Bloomberg": [],
    "Bonus Portal": [],
    "Canva": [
        "User Access & Permission",
        "Something else",
    ],
    "CollegeHouse": [],
    "Community Rewards": [
        "Add/Remove User",
        "Add/Remove Property Access",
        "Rewards Program Question or Issue",
        "Incentives Program Question or Issue",
    ],
    "Corporate Server (TPCO CITRIX + Remanage)": [
        "Cannot Connect to VPN",
        "Cannot Access Network Folder",
        "Cannot Access Remanage",
    ],
    "Courtesy Connection": [
        "User Account Issue (new/add/remove)",
        "Urgent Issue (not receiving messages)",
        "Other Issue (still able to receive messages)",
    ],
    "Email Distribution Lists": [
        "Add/remove user",
        "Create List",
    ],
    "Flex": [],
    "Document or Tutorial Request": [],
    "Entrata - Utilities (Edition on Oberlin)": [],
    "Epitiro": [],
    "EZ Turn": [
        "Add/Remove Users",
        "Other",
    ],
    "GeoKey (Smart Locks)": [],
    "Google Chrome": [
        "Chrome Not Working",
        "Reinstall Chrome",
        "Update Chrome",
        "Other",
    ],
    "Google Sheets/Excel - RO, Electric, Bonus Form, Budget, Master Dashboard, etc.": [],
    "Grace Hill PerformanceHQ": [
        "Add/remove user",
        "Add course(s) to employee(s)",
        "Cannot login/forgot password",
        "Other Issue",
    ],
    "Grata (Smart Locks)": [],
    "HelloSign/DocuSign/Adobe Sign": [],
    "Homebase (Smart Locks)": [],
    "Hyly - Email Blasts & Drip Campaigns": [],
    "ILS - Apartments.com, Rent.com, etc": [
        "Listing Updates",
        "Integrations",
        "Something Else",
    ],
    "Insurance - DPPSCIC / Stern / ePremium": [
        "ePremium",
        "DPPSCIC",
        "Stern",
    ],
    "Leap": [],
    "Loaner Request/Checkout (laptops, hotspots, etc)": [
        "Laptop",
        "Hotspot",
        "Other",
    ],
    "Lock Systems": [],
    "Maintenance Supply Companies (HD, Lowes, Ferguson, Chadwell)": [
        "Order Login (issue or new account request)",
        "Invoice Gateway Login (issue or new account request)",
        "Request Purchase Card",
        "Something else",
    ],
    "MailChimp/iContact": [],
    "Microsoft Office": [
        "Office Not Working",
        "MS Word Not Working",
        "Excel Not Working",
        "Quote for Purchase",
        "Other",
    ],
    "Mood Media - Music": [
        "Mood Music - Profusion iS Streaming Box",
        "Mood Music - Mood Mix iPad app",
        "Mood TV",
    ],
    "National Credit Systems (NCS) - Collections": [
        "Reset Password",
        "Update Report Recipients",
        "Need guidance (how to's) or other support",
    ],
    "Nationwide Eviction": [],
    "Network/Internet": [
        "Internet Service Outage",
        "Not Connecting to Network",
        "Other",
    ],
    "Notifii Packages": [],
    "Staples (Office Supplies)": [],
    "Package Lockers - Luxer One, Parcel Pending, Amazon Hub": [],
    "Paylease/Zego": [],
    "PayReady Collections": [
        "Support",
    ],
    "Phone": [
        "Phone Service Outage",
        "Phone Not Working",
        "Other",
    ],
    "Property Website": [
        "Update Specials",
        "Update office hours",
        "Websites Issues/Edits",
        "Virtual Tours - Panoskin, LCP360, Peek",
    ],
    "QR Codes": [],
    "Quickbooks": [],
    "Quote Request - Hardware/Devices or Software": [],
    "RentPlus/Homebody Rent Reporting": [
        "User Login",
        "Other",
    ],
    "Reviews/Reputation/Surveys - Opiniion, J Turner, Yelp, Google Business": [
        "Update office hours",
        "Opiniion",
        "J Turner ORA Scores",
        "Yelp",
        "Google Business",
    ],
    "SmartRent (Smart Locks)": [],
    "Social Media - Facebook, Instagram, Google Business": [
        "Update office hours",
        "Ads/boosted content",
        "Password change submission",
        "Password/access issues",
        "Tips/Tricks/Training",
    ],
    "Stratis (Smart Locks)": [],
    "Student.com": [
        "Add/remove user",
        "Login issue",
        "Other issue",
    ],
    "Tawk.to": [
        "Add/Remove User",
        "Other Support",
    ],
    "Tour24": [
        "Add/Remove User",
        "Turn On/Off Tours",
        "Script Changes",
        "Other Support",
    ],
    "Travtus": [
        "Chatbot Issue",
        "Review Response Issue",
        "Gateway Issue",
        "Need Access",
        "Other",
    ],
    "UHomes": [],
    "Update Office Hours": [],
    "Utilities - SimpleBills, Conservice, AUM": [],
    "Yet Another Mail Merge (YAMM)": [
        "Add/remove user",
        "Need guidance (how to's) or other support",
    ],
    "Zoom Conferencing": [],
    "Other - do not use": [
        "HR Use Only",
        "Non-handled tickets",
    ],
}


def more_detail_options(system: str) -> list[str]:
    """Level-2 "Issue" options valid for a given System value.

    Returns [] for systems with no nested options (36 of 77) and for
    unknown/blank system strings, so callers can render an empty dropdown
    without a KeyError.
    """
    return MORE_DETAIL_BY_SYSTEM.get(system, [])
