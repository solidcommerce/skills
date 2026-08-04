#!/usr/bin/env python3
"""Service-to-log-source routing engine for the Solid Commerce platform.

Maps service names to their correct log backends (Azure Blob, SQL Server, SMB)
with fuzzy matching and sub-service discovery.
"""

import argparse
import json
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Routing table data
# ---------------------------------------------------------------------------

# Each entry: { service_name, category, sources: [ordered by priority], smb_subfolder, sql_table, related }
# Sources list: [{ type, container, sub_container?, path_prefix_template }]

# Category A: Azure Functions → openretail container (lowercase names)
_AZURE_FUNCTIONS = [
    "SC.System.Invoice", "SC.System.CRM", "SC.System.Inventory",
    "SC.System.AutomationRules.API", "SC.System.AutomationRules.Logging",
    "SC.System.AutomationRules.Processor",
    "SC.System.Carts.Shopify", "SC.System.Carts.Shopify.RealTimeOrders",
    "SC.System.Marketplaces.Amazon", "SC.System.Marketplaces.eBay",
    "SC.System.Marketplaces.Etsy", "SC.System.Marketplaces.Backmarket",
    "SC.System.Marketplaces.Walmart",
    "SC.System.API.MobileApp", "SC.System.API.PurchaseOrder",
    "SC.System.API.DynamicCostRules",
    "SC.System.Shipping.Drafts", "SC.System.Kit", "SC.System.Tags",
    "CorpAdmin.Accounting.Billing", "CorpAdmin.Accounting.FeaturePlanning",
    "CorpAdmin.Accounting.FeaturePricing",
    "Custom.Customers.AGSolutions", "Custom.Customers.AdventureMoto",
    "Custom.Customers.BlueDeltaJeans", "Custom.Customers.DashcamStore",
    "Custom.Customers.LibertyCoin", "Custom.Customers.WBK",
    "Vendors.Turn14.Inventory", "Vendors.Turn14.Pricing",
]

# Category B: Windows Services → services-logs (ZIP), SMB LDS_Services
_SERVICES_LOGS = [
    "LDS_3DCartOrdersSync", "LDS_3DCartProductLister", "LDS_3DCartProductsImport",
    "LDS_3DCartQtySync", "LDS_3DCartRepricer", "LDS_ASNExport",
    "LDS_AmazonFBAInventoryAndOrdersSync", "LDS_AmazonOrdersSync",
    "LDS_AutomateAmazonListing", "LDS_AutomateEbayListings",
    "LDS_BigCommerceOrdersSync", "LDS_BigCommerceProductLister",
    "LDS_BigCommerceProductsImport", "LDS_BigCommerceQtySync",
    "LDS_BigCommerceRepricer", "LDS_DropshipOrderAckExport", "LDS_EMails",
    "LDS_FileUploader", "LDS_ImagesImport", "LDS_InventoryExport",
    "LDS_KeystoneInventoryImport", "LDS_ListerAmazon",
    "LDS_MagentoOrdersSync", "LDS_MagentoProductLister",
    "LDS_MagentoProductsImport", "LDS_MagentoQtyUpdater",
    "LDS_MagentoRepricer", "LDS_MagentoReverseInventory",
    "LDS_OrderImport", "LDS_OrderModificationImport",
    "LDS_OverstockOrdersSync", "LDS_OverstockQtySync",
    "LDS_OverstockShipmentSync", "LDS_POLister", "LDS_POManagedQtyUpdater",
    "LDS_POProcessing", "LDS_POrdersSync", "LDS_PartsUnlimitedSync",
    "LDS_ProductReturnExport", "LDS_ProductReturnResponseImport",
    "LDS_QtyUpdaterEbayAuction", "LDS_RepricerAmazon",
    "LDS_RepricerEbayAuctions", "LDS_SearsOrdersSync",
    "LDS_SearsProductLister", "LDS_SearsQtySync", "LDS_SearsRepricer",
    "LDS_SyncInventoriesAmazon", "LDS_SyncSolidCommerceVendors",
    "LDS_VolusionOrdersSync", "LDS_VolusionProductsImport",
    "LDS_VolusionProductsLister", "LDS_VolusionQtySync",
    "LDS_VolusionRepricer", "LDS_WPSProductsSync",
    "LDS_YahooImportProduct", "LDS_YahooOrderSync",
    "LDS_YahooProductLister", "LDS_YahooQtySync", "LDS_YahooRepricer",
    "LDS_eBayImageUploader", "LDS_eBayListingWorker",
    "LDS_eBayOfferEventsSync", "LDS_eBayPlatformSync",
    "LDS_eBayUpdaterWorker",
    "SC.InventoryLevelNotifcation.Service",
    "SC.Marketplace.Engine.AutoImport",
    "SC.Marketplace.Engine.FulfillmentLagTime",
    "SC.Marketplace.Engine.InventorySync", "SC.Marketplace.Engine.Listing",
    "SC.Marketplace.Engine.MarketItemMaintenance",
    "SC.Marketplace.Engine.OrderImport", "SC.Marketplace.Engine.PriceSync",
    "SC.Marketplace.Engine.Refunds", "SC.Marketplace.Engine.Returns",
    "SC.Marketplace.Engine.ShipmentUpdate",
    "SC.Marketplace.Engine.WalmartShippingTemplates",
    "SC.Marketplace.Manager", "SC.NotificationUnitsProcessing.Service",
    "SC.OrderAutomationAddressValidation.Service",
    "SC.OrderAutomationAzureEventGrid.Service",
    "SC.OrderAutomationDeliveryTracking.Service",
    "SC.OrderAutomationMarketingInsertsRules.Service",
    "SC.OrderAutomationProximityRules.Service",
    "SC.ServiceEngineWorker.2", "SC.ServiceEngineWorker.3",
    "SC.ServiceEngineWorker.4", "SC.ServiceEngineWorker.5",
    "SC.ServiceWorker.1", "SC.ServiceWorker.2",
]

# Category C: Vendor Services → services-logs + SMB SC_Services
_VENDOR_SERVICES = [
    "Vendors.WPS", "Vendors.NYWD", "Vendors.IngramMicro", "Vendors.ATD",
    "Vendors.WheelPros", "Vendors.HoneysPlace", "Vendors.Autoforce",
    "Vendors.PartsUnlimited", "Vendors.KGHLogistics", "Vendors.NTW",
    "Vendors.PremierPerformance",
]

# Category D: Amazon-specific → SMB LDS_Amazon_Services + services-logs
_AMAZON_SPECIFIC = [
    "SC.System.Marketplaces.Amazon.RealTimeRepricer",
    "SC.System.Marketplaces.Amazon.CodeGeneration",
]

# Category E: Web/API → web-logs + SMB Web_Logs + SQL weblogs
_WEB_APIS = [
    "AuthAPI", "IntegrationAPI", "InventoryAPI", "NotificationsAPI",
    "OrdersAPI", "PortalAPI", "PrintingAPI", "ProductsAPI",
    "SalesChannelsAPI", "SendGridWebhookApi", "ShippingAPI",
    "WebServices", "WebSite",
]
_WEB_FRONTENDS = [
    "SC.Base.API.FrontEnd.General", "SC.Base.FrontEnd.Core",
    "SC.Internal.FrontEnd.Core", "SC.Internal.API.DevOps",
    "Integrations.IntegrationPortal",
]

# Category F: Legacy DB logging → SQL appslogs + services-logs
_LEGACY_DB = [
    "GrouponOrdersSync", "GrouponTrackingSync", "SPSCommerce",
]

# Category G: Messaging & AI → openretail applogs
_MESSAGING_AI = [
    "SC.System.Marketplaces.eBay.MessagingApp",
    "SC.System.Marketplaces.Messaging.Autoreply",
    "AI.AutoReplyAgent",
]

# Sub-service dependency map (max 1 level deep)
_RELATED_SERVICES: dict[str, list[str]] = {
    # OrdersSync → OrderImport engine
    "OrdersSync": ["SC.Marketplace.Engine.OrderImport"],
    "OrderSync": ["SC.Marketplace.Engine.OrderImport"],
    "OrderImport": ["SC.Marketplace.Engine.OrderImport"],
    # QtySync → InventorySync engine
    "QtySync": ["SC.Marketplace.Engine.InventorySync"],
    "QtyUpdater": ["SC.Marketplace.Engine.InventorySync"],
    "InventorySync": ["SC.Marketplace.Engine.InventorySync"],
    # ProductLister → Listing engine
    "ProductLister": ["SC.Marketplace.Engine.Listing"],
    "ProductsImport": ["SC.Marketplace.Engine.Listing"],
    "Lister": ["SC.Marketplace.Engine.Listing"],
    # Repricer → PriceSync engine
    "Repricer": ["SC.Marketplace.Engine.PriceSync"],
    "RepricerAmazon": ["SC.Marketplace.Engine.PriceSync"],
    "RepricerEbayAuctions": ["SC.Marketplace.Engine.PriceSync"],
    # Shipment → ShipmentUpdate engine
    "ShipmentSync": ["SC.Marketplace.Engine.ShipmentUpdate"],
    "ShipmentUpdate": ["SC.Marketplace.Engine.ShipmentUpdate"],
    # Shopify
    "SC.System.Carts.Shopify": ["SC.Marketplace.Engine.OrderImport", "SC.Marketplace.Engine.InventorySync"],
    "SC.System.Carts.Shopify.RealTimeOrders": ["SC.Marketplace.Engine.OrderImport"],
    # BigCommerce
    "LDS_BigCommerceOrdersSync": ["SC.Marketplace.Engine.OrderImport"],
    "LDS_BigCommerceQtySync": ["SC.Marketplace.Engine.InventorySync"],
    # Amazon
    "LDS_AmazonOrdersSync": ["SC.Marketplace.Engine.OrderImport", "LDS_SyncInventoriesAmazon"],
    "LDS_AmazonFBAInventoryAndOrdersSync": ["SC.Marketplace.Engine.OrderImport"],
    # Magento
    "LDS_MagentoOrdersSync": ["SC.Marketplace.Engine.OrderImport"],
    "LDS_MagentoQtyUpdater": ["SC.Marketplace.Engine.InventorySync"],
}

# Common aliases for fuzzy matching
_ALIASES: dict[str, list[str]] = {
    "shopify": ["SC.System.Carts.Shopify", "SC.System.Carts.Shopify.RealTimeOrders"],
    "ebay": ["LDS_eBayListingWorker", "LDS_eBayPlatformSync", "LDS_eBayOfferEventsSync",
             "LDS_eBayImageUploader", "LDS_eBayUpdaterWorker", "SC.System.Marketplaces.eBay"],
    "amazon": ["LDS_AmazonOrdersSync", "LDS_AmazonFBAInventoryAndOrdersSync",
               "LDS_RepricerAmazon", "LDS_SyncInventoriesAmazon", "LDS_ListerAmazon",
               "SC.System.Marketplaces.Amazon", "SC.System.Marketplaces.Amazon.RealTimeRepricer",
               "SC.System.Marketplaces.Amazon.CodeGeneration"],
    "walmart": ["SC.System.Marketplaces.Walmart", "SC.Marketplace.Engine.WalmartShippingTemplates"],
    "etsy": ["SC.System.Marketplaces.Etsy"],
    "backmarket": ["SC.System.Marketplaces.Backmarket"],
    "magento": ["LDS_MagentoOrdersSync", "LDS_MagentoProductLister", "LDS_MagentoProductsImport",
                "LDS_MagentoQtyUpdater", "LDS_MagentoRepricer", "LDS_MagentoReverseInventory"],
    "bigcommerce": ["LDS_BigCommerceOrdersSync", "LDS_BigCommerceProductLister",
                    "LDS_BigCommerceProductsImport", "LDS_BigCommerceQtySync", "LDS_BigCommerceRepricer"],
    "volusion": ["LDS_VolusionOrdersSync", "LDS_VolusionProductsImport",
                 "LDS_VolusionProductsLister", "LDS_VolusionQtySync", "LDS_VolusionRepricer"],
    "sears": ["LDS_SearsOrdersSync", "LDS_SearsProductLister", "LDS_SearsQtySync", "LDS_SearsRepricer"],
    "yahoo": ["LDS_YahooImportProduct", "LDS_YahooOrderSync", "LDS_YahooProductLister",
              "LDS_YahooQtySync", "LDS_YahooRepricer"],
    "3dcart": ["LDS_3DCartOrdersSync", "LDS_3DCartProductLister", "LDS_3DCartProductsImport",
               "LDS_3DCartQtySync", "LDS_3DCartRepricer"],
    "overstock": ["LDS_OverstockOrdersSync", "LDS_OverstockQtySync", "LDS_OverstockShipmentSync"],
    "fishbowl": ["SC_Fishbowl_InventorySync", "SC_Fishbowl_OrdersSync", "SC_Fishbowl_ProductsSync"],
    "skuvault": ["SKUVault_Integration"],
    "shipstation": ["ShipStation_Integration"],
    "orders": ["LDS_AmazonOrdersSync", "LDS_BigCommerceOrdersSync", "LDS_MagentoOrdersSync",
               "LDS_VolusionOrdersSync", "LDS_SearsOrdersSync", "LDS_OverstockOrdersSync",
               "LDS_3DCartOrdersSync", "LDS_YahooOrderSync", "LDS_OrderImport",
               "SC.Marketplace.Engine.OrderImport"],
    "inventory": ["SC.System.Inventory", "SC.Marketplace.Engine.InventorySync",
                  "LDS_InventoryExport", "SC.InventoryLevelNotifcation.Service"],
    "shipping": ["SC.System.Shipping.Drafts", "SC.Marketplace.Engine.ShipmentUpdate",
                 "ShippingAPI"],
    "groupon": ["GrouponOrdersSync", "GrouponTrackingSync"],
    "fragrance": ["FragranceX_Integration_OrdersSync", "FragranceX_Integration_TrackingSync"],
}


def _build_service_entry(name: str, category: str, sources: list[dict],
                         smb_subfolder: Optional[str], sql_table: Optional[str]) -> dict:
    """Build a service routing entry."""
    related = _find_related(name)
    return {
        "service_name": name,
        "category": category,
        "sources": sources,
        "smb_subfolder": smb_subfolder,
        "sql_table": sql_table,
        "related_services": related,
    }


def _find_related(service_name: str) -> list[str]:
    """Find related sub-services for a given service (max 1 level)."""
    related: list[str] = []

    # Check direct match first
    if service_name in _RELATED_SERVICES:
        related.extend(_RELATED_SERVICES[service_name])

    # Check suffix-based patterns
    for suffix, deps in _RELATED_SERVICES.items():
        if service_name.endswith(suffix) and service_name != suffix:
            for dep in deps:
                if dep not in related and dep != service_name:
                    related.append(dep)

    return related


def _build_routing_table() -> dict[str, dict]:
    """Build the complete routing table keyed by lowercase service name."""
    table: dict[str, dict] = {}

    # Category A: Azure Functions → openretail
    for svc in _AZURE_FUNCTIONS:
        lower = svc.lower()
        entry = _build_service_entry(
            name=svc,
            category="azure_function",
            sources=[
                {"type": "blob", "container": "openretail", "sub_container": "applogs",
                 "path_prefix": f"applogs/{{date}}/{lower}"},
                {"type": "blob", "container": "openretail", "sub_container": "rrlogs",
                 "path_prefix": f"rrlogs/{{date}}/{lower}"},
            ],
            smb_subfolder=None,
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    # Category B: Windows Services → services-logs
    for svc in _SERVICES_LOGS:
        entry = _build_service_entry(
            name=svc,
            category="windows_service",
            sources=[
                {"type": "smb", "subfolder": "LDS_Services"},
                {"type": "blob", "container": "services-logs",
                 "path_prefix": f"{{date}}/{svc}"},
            ],
            smb_subfolder="LDS_Services",
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    # Category C: Vendor Services → services-logs + SC_Services
    for svc in _VENDOR_SERVICES:
        entry = _build_service_entry(
            name=svc,
            category="vendor_service",
            sources=[
                {"type": "smb", "subfolder": "SC_Services"},
                {"type": "blob", "container": "services-logs",
                 "path_prefix": f"{{date}}/{svc}"},
            ],
            smb_subfolder="SC_Services",
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    # Category D: Amazon-specific → LDS_Amazon_Services + services-logs
    for svc in _AMAZON_SPECIFIC:
        entry = _build_service_entry(
            name=svc,
            category="amazon_specific",
            sources=[
                {"type": "smb", "subfolder": "LDS_Amazon_Services"},
                {"type": "blob", "container": "services-logs",
                 "path_prefix": f"{{date}}/{svc}"},
            ],
            smb_subfolder="LDS_Amazon_Services",
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    # Category E: Web/API → web-logs + Web_Logs + SQL weblogs
    for svc in _WEB_APIS:
        entry = _build_service_entry(
            name=svc,
            category="web_api",
            sources=[
                {"type": "blob", "container": "web-logs",
                 "path_prefix": f"{{date}}/{svc}"},
                {"type": "smb", "subfolder": "Web_Logs"},
                {"type": "sql", "table": "weblogs"},
            ],
            smb_subfolder="Web_Logs",
            sql_table="weblogs",
        )
        table[svc.lower()] = entry

    for svc in _WEB_FRONTENDS:
        entry = _build_service_entry(
            name=svc,
            category="web_frontend",
            sources=[
                {"type": "blob", "container": "web-logs",
                 "path_prefix": f"{{date}}/{svc}"},
                {"type": "smb", "subfolder": "Web_Logs"},
                {"type": "sql", "table": "weblogs"},
            ],
            smb_subfolder="Web_Logs",
            sql_table="weblogs",
        )
        table[svc.lower()] = entry

    # Category F: Legacy DB → SQL appslogs + services-logs
    for svc in _LEGACY_DB:
        entry = _build_service_entry(
            name=svc,
            category="legacy_db",
            sources=[
                {"type": "sql", "table": "appslogs"},
                {"type": "blob", "container": "services-logs",
                 "path_prefix": f"{{date}}/{svc}"},
            ],
            smb_subfolder=None,
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    # Category G: Messaging & AI → openretail
    for svc in _MESSAGING_AI:
        lower = svc.lower()
        entry = _build_service_entry(
            name=svc,
            category="messaging_ai",
            sources=[
                {"type": "blob", "container": "openretail", "sub_container": "applogs",
                 "path_prefix": f"applogs/{{date}}/{lower}"},
            ],
            smb_subfolder=None,
            sql_table="appslogs",
        )
        table[svc.lower()] = entry

    return table


# Singleton routing table
_ROUTING_TABLE = _build_routing_table()


def lookup_exact(service_name: str) -> list[dict]:
    """Exact (case-insensitive) lookup."""
    key = service_name.lower().strip()
    if key in _ROUTING_TABLE:
        return [_ROUTING_TABLE[key]]
    return []


def lookup_fuzzy(query: str) -> list[dict]:
    """Fuzzy lookup: aliases, substring match, keyword extraction."""
    query_lower = query.lower().strip()
    results: list[dict] = []
    seen: set[str] = set()

    # 1. Check aliases
    for alias, service_names in _ALIASES.items():
        if alias in query_lower:
            for svc in service_names:
                key = svc.lower()
                if key in _ROUTING_TABLE and key not in seen:
                    results.append(_ROUTING_TABLE[key])
                    seen.add(key)

    # 2. Substring match on service names
    for key, entry in _ROUTING_TABLE.items():
        if key in seen:
            continue
        # Match against the canonical name or the key
        if query_lower in key or query_lower in entry["service_name"].lower():
            results.append(entry)
            seen.add(key)

    # 3. Token-based match: strip common prefixes and match core terms
    tokens = query_lower.replace("_", " ").replace(".", " ").split()
    # Remove noise words
    noise = {"lds", "sc", "system", "marketplace", "marketplaces", "engine",
             "service", "services", "integration", "the", "for", "log", "logs"}
    meaningful_tokens = [t for t in tokens if t not in noise and len(t) > 2]

    if meaningful_tokens:
        for key, entry in _ROUTING_TABLE.items():
            if key in seen:
                continue
            name_lower = entry["service_name"].lower().replace("_", " ").replace(".", " ")
            if all(tok in name_lower for tok in meaningful_tokens):
                results.append(entry)
                seen.add(key)

    return results


def list_all_services() -> list[dict]:
    """Return all services sorted by category then name."""
    entries = sorted(_ROUTING_TABLE.values(), key=lambda e: (e["category"], e["service_name"]))
    return entries


def route_service(service_name: str, fuzzy: bool = False) -> dict:
    """Main routing function. Returns JSON-serializable result."""
    # Try exact match first
    matches = lookup_exact(service_name)

    if not matches:
        # Always try fuzzy if exact fails
        matches = lookup_fuzzy(service_name)

    if not matches and not fuzzy:
        # If no fuzzy flag and no matches, suggest trying fuzzy
        return {
            "query": service_name,
            "matched_services": [],
            "suggestions": [
                f"No exact match for '{service_name}'. Try --fuzzy for broader matching.",
                "Use --list-all to see all known services.",
            ],
        }

    return {
        "query": service_name,
        "matched_services": matches,
        "suggestions": [] if matches else [
            f"No services matched '{service_name}'.",
            "Use --list-all to see all known services.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route a service name to its log sources (Blob, SQL, SMB).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --service "AmazonOrdersSync"
  %(prog)s --service "shopify orders" --fuzzy
  %(prog)s --list-all
        """,
    )
    parser.add_argument("--service", type=str, help="Service name to look up")
    parser.add_argument("--fuzzy", action="store_true",
                        help="Enable fuzzy matching (default: exact first, fuzzy fallback)")
    parser.add_argument("--list-all", action="store_true",
                        help="List all known services with their sources")

    args = parser.parse_args()

    if not args.service and not args.list_all:
        parser.error("Either --service or --list-all is required")

    if args.list_all:
        entries = list_all_services()
        output = {
            "total_services": len(entries),
            "services": [
                {
                    "service_name": e["service_name"],
                    "category": e["category"],
                    "sources": [s.get("type") for s in e["sources"]],
                    "smb_subfolder": e["smb_subfolder"],
                }
                for e in entries
            ],
        }
        json.dump(output, sys.stdout, indent=2)
        print()
        sys.exit(0)

    result = route_service(args.service, fuzzy=args.fuzzy)
    json.dump(result, sys.stdout, indent=2)
    print()

    if not result["matched_services"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
