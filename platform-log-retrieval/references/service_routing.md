# Service Routing Table

Complete mapping of 117+ Solid Commerce platform services to their log sources.

## Table of Contents
- [Category A: Azure Functions](#category-a-azure-functions)
- [Category B: Windows Services (services-logs)](#category-b-windows-services)
- [Category C: Vendor Services](#category-c-vendor-services)
- [Category D: Amazon-Specific](#category-d-amazon-specific)
- [Category E: Web/API Services](#category-e-webapi-services)
- [Category F: Legacy (DB Logging)](#category-f-legacy-db-logging)
- [Category G: Messaging & AI](#category-g-messaging--ai)
- [Blob Container Service Lists](#blob-container-service-lists)

---

## Category A: Azure Functions

**Route:** Blob `openretail` container (applogs/rrlogs sub-containers) → lowercase names

These are Azure Function apps. Their logs go to the `openretail` blob container with lowercase naming convention.

| Service | Blob Path (openretail) | Notes |
|---------|----------------------|-------|
| SC.System.Invoice | `applogs/{date}/sc.system.invoice/` | Invoicing |
| SC.System.CRM | `applogs/{date}/sc.system.crm/` | CRM |
| SC.System.Inventory | `applogs/{date}/sc.system.inventory/` | Inventory management |
| SC.System.AutomationRules.API | `applogs/{date}/sc.system.automationrules.api/` | Automation rules API |
| SC.System.AutomationRules.Logging | `applogs/{date}/sc.system.automationrules.logging/` | Automation rules logging |
| SC.System.AutomationRules.Processor | `applogs/{date}/sc.system.automationrules.processor/` | Automation rules processor |
| SC.System.Carts.Shopify | `applogs/{date}/sc.system.carts.shopify/` | Shopify cart integration |
| SC.System.Carts.Shopify.RealTimeOrders | `applogs/{date}/sc.system.carts.shopify.realtimeorders/` | Shopify real-time orders |
| SC.System.Marketplaces.Amazon | `applogs/{date}/sc.system.marketplaces.amazon/` | Amazon marketplace |
| SC.System.Marketplaces.eBay | `applogs/{date}/sc.system.marketplaces.ebay/` | eBay marketplace |
| SC.System.Marketplaces.Etsy | `applogs/{date}/sc.system.marketplaces.etsy/` | Etsy marketplace |
| SC.System.Marketplaces.Backmarket | `applogs/{date}/sc.system.marketplaces.backmarket/` | Backmarket |
| SC.System.Marketplaces.Walmart | `applogs/{date}/sc.system.marketplaces.walmart/` | Walmart marketplace |
| SC.System.API.MobileApp | `applogs/{date}/sc.system.api.mobileapp/` | Mobile app API |
| SC.System.API.PurchaseOrder | `applogs/{date}/sc.system.api.purchaseorder/` | Purchase order API |
| SC.System.API.DynamicCostRules | `applogs/{date}/sc.system.api.dynamiccostrules/` | Dynamic cost rules |
| SC.System.Shipping.Drafts | `applogs/{date}/sc.system.shipping.drafts/` | Shipping drafts |
| SC.System.Kit | `applogs/{date}/sc.system.kit/` | Kit management |
| SC.System.Tags | `applogs/{date}/sc.system.tags/` | Tag management |
| CorpAdmin.Accounting.Billing | `applogs/{date}/corpadmin.accounting.billing/` | Billing |
| CorpAdmin.Accounting.FeaturePlanning | `applogs/{date}/corpadmin.accounting.featureplanning/` | Feature planning |
| CorpAdmin.Accounting.FeaturePricing | `applogs/{date}/corpadmin.accounting.featurepricing/` | Feature pricing |
| Custom.Customers.AGSolutions | `applogs/{date}/custom.customers.agsolutions/` | Custom: AG Solutions |
| Custom.Customers.AdventureMoto | `applogs/{date}/custom.customers.adventuremoto/` | Custom: Adventure Moto |
| Custom.Customers.BlueDeltaJeans | `applogs/{date}/custom.customers.bluedeltajeans/` | Custom: Blue Delta Jeans |
| Custom.Customers.DashcamStore | `applogs/{date}/custom.customers.dashcamstore/` | Custom: Dashcam Store |
| Custom.Customers.LibertyCoin | `applogs/{date}/custom.customers.libertycoin/` | Custom: Liberty Coin |
| Custom.Customers.WBK | `applogs/{date}/custom.customers.wbk/` | Custom: WBK |
| Vendors.Turn14.Inventory | `applogs/{date}/vendors.turn14.inventory/` | Turn14 inventory feed |
| Vendors.Turn14.Pricing | `applogs/{date}/vendors.turn14.pricing/` | Turn14 pricing feed |

---

## Category B: Windows Services

**Route:** SMB network share (real-time, < 4 hours) → Blob `services-logs` (historical)

All 90 services in the `services-logs` blob container. ZIP format, hourly files.

**Blob path:** `{date}/{ServiceName}/{ServerName}/AppFallback/{date}-{HH}.zip`

### Services with Known SMB Mappings

| Service | Windows Service Name | SMB Subfolder | Log Path (on server) |
|---------|---------------------|---------------|---------------------|
| SC_Fishbowl_InventorySync | SC_Fishbowl_InventorySync | LDS_Services | D:\Logs\FishBowl\InventorySync\{date}.log |
| SC_Fishbowl_OrdersSync | SC_Fishbowl_OrdersSync | LDS_Services | D:\Logs\FishBowl\OrdersSync\{date}.log |
| SC_Fishbowl_ProductsSync | SC_Fishbowl_ProductSync | LDS_Services | D:\Logs\FishBowl\ProductSync\{date}.log |
| *_SKUVault_Integration (5 svc) | *_SKUVault_Integration | LDS_Services | D:\Logs\SkuVault\{date}.log |
| ShipStation_Integration | ShipStation_Integration | LDS_Services | D:\Logs\Shipstation\{date}.log |
| ShipwireIntegration | ShipwireIntegration | LDS_Services | D:\Logs\Shipware{date}.txt |
| InfoPlus_Integration | InfoPlus_Integration | LDS_Services | D:\Logs\InfoPlus\{date}.log |
| SOS_Inventory_Integration | SOS_Inventory_Integration | LDS_Services | D:\Logs\Sos_Inventory_Integration.txt |
| SC_UAG_FBA_Export | SC_UAG_FBA_Export | LDS_Services | D:\Logs\Export.txt |
| FragranceX_Integration_OrdersSync | FragranceX_Integration_OrdersSync | LDS_Services | N/A |
| FragranceX_Integration_TrackingSync | FragranceX_Integration_TrackingSync | LDS_Services | N/A |

### Full services-logs Service List

```
LDS_3DCartOrdersSync, LDS_3DCartProductLister, LDS_3DCartProductsImport,
LDS_3DCartQtySync, LDS_3DCartRepricer, LDS_ASNExport,
LDS_AmazonFBAInventoryAndOrdersSync, LDS_AmazonOrdersSync,
LDS_AutomateAmazonListing, LDS_AutomateEbayListings,
LDS_BigCommerceOrdersSync, LDS_BigCommerceProductLister,
LDS_BigCommerceProductsImport, LDS_BigCommerceQtySync,
LDS_BigCommerceRepricer, LDS_DropshipOrderAckExport, LDS_EMails,
LDS_FileUploader, LDS_ImagesImport, LDS_InventoryExport,
LDS_KeystoneInventoryImport, LDS_ListerAmazon, LDS_MagentoOrdersSync,
LDS_MagentoProductLister, LDS_MagentoProductsImport,
LDS_MagentoQtyUpdater, LDS_MagentoRepricer, LDS_MagentoReverseInventory,
LDS_OrderImport, LDS_OrderModificationImport, LDS_OverstockOrdersSync,
LDS_OverstockQtySync, LDS_OverstockShipmentSync, LDS_POLister,
LDS_POManagedQtyUpdater, LDS_POProcessing, LDS_POrdersSync,
LDS_PartsUnlimitedSync, LDS_ProductReturnExport,
LDS_ProductReturnResponseImport, LDS_QtyUpdaterEbayAuction,
LDS_RepricerAmazon, LDS_RepricerEbayAuctions, LDS_SearsOrdersSync,
LDS_SearsProductLister, LDS_SearsQtySync, LDS_SearsRepricer,
LDS_SyncInventoriesAmazon, LDS_SyncSolidCommerceVendors,
LDS_VolusionOrdersSync, LDS_VolusionProductsImport,
LDS_VolusionProductsLister, LDS_VolusionQtySync, LDS_VolusionRepricer,
LDS_WPSProductsSync, LDS_YahooImportProduct, LDS_YahooOrderSync,
LDS_YahooProductLister, LDS_YahooQtySync, LDS_YahooRepricer,
LDS_eBayImageUploader, LDS_eBayListingWorker, LDS_eBayOfferEventsSync,
LDS_eBayPlatformSync, LDS_eBayUpdaterWorker,
SC.InventoryLevelNotifcation.Service,
SC.Marketplace.Engine.AutoImport,
SC.Marketplace.Engine.FulfillmentLagTime,
SC.Marketplace.Engine.InventorySync, SC.Marketplace.Engine.Listing,
SC.Marketplace.Engine.MarketItemMaintenance,
SC.Marketplace.Engine.OrderImport, SC.Marketplace.Engine.PriceSync,
SC.Marketplace.Engine.Refunds, SC.Marketplace.Engine.Returns,
SC.Marketplace.Engine.ShipmentUpdate,
SC.Marketplace.Engine.WalmartShippingTemplates,
SC.Marketplace.Manager, SC.NotificationUnitsProcessing.Service,
SC.OrderAutomationAddressValidation.Service,
SC.OrderAutomationAzureEventGrid.Service,
SC.OrderAutomationDeliveryTracking.Service,
SC.OrderAutomationMarketingInsertsRules.Service,
SC.OrderAutomationProximityRules.Service,
SC.ServiceEngineWorker.2, SC.ServiceEngineWorker.3,
SC.ServiceEngineWorker.4, SC.ServiceEngineWorker.5,
SC.ServiceWorker.1, SC.ServiceWorker.2
```

---

## Category C: Vendor Services

**Route:** Blob `services-logs` + SMB `SC_Services`

| Vendor Service | Blob Container | SMB Subfolder |
|----------------|---------------|---------------|
| Vendors.WPS | services-logs | SC_Services |
| Vendors.Turn14 | applogs (openretail) | SC_Services |
| Vendors.NYWD | services-logs | SC_Services |
| Vendors.IngramMicro | services-logs | SC_Services |
| Vendors.ATD | services-logs | SC_Services |
| Vendors.WheelPros | services-logs | SC_Services |
| Vendors.HoneysPlace | services-logs | SC_Services |
| Vendors.Autoforce | services-logs | SC_Services |
| Vendors.PartsUnlimited | services-logs | SC_Services |
| Vendors.KGHLogistics | services-logs | SC_Services |
| Vendors.NTW | services-logs | SC_Services |
| Vendors.PremierPerformance | services-logs | SC_Services |

---

## Category D: Amazon-Specific

**Route:** SMB `LDS_Amazon_Services` → Blob `services-logs`

| Service | SMB Subfolder | Blob Container |
|---------|--------------|----------------|
| SC.System.Marketplaces.Amazon.RealTimeRepricer | LDS_Amazon_Services | services-logs |
| SC.System.Marketplaces.Amazon.CodeGeneration | LDS_Amazon_Services | services-logs |
| Amazon marketplace engine services | LDS_Amazon_Services | services-logs |

---

## Category E: Web/API Services

**Route:** Blob `web-logs` → SMB `Web_Logs` → SQL `weblogs` table

### web-logs Container (13 APIs)

| API | Blob Path | SMB Subfolder |
|-----|-----------|---------------|
| AuthAPI | `{date}/AuthAPI/` | Web_Logs |
| IntegrationAPI | `{date}/IntegrationAPI/` | Web_Logs |
| InventoryAPI | `{date}/InventoryAPI/` | Web_Logs |
| NotificationsAPI | `{date}/NotificationsAPI/` | Web_Logs |
| OrdersAPI | `{date}/OrdersAPI/` | Web_Logs |
| PortalAPI | `{date}/PortalAPI/` | Web_Logs |
| PrintingAPI | `{date}/PrintingAPI/` | Web_Logs |
| ProductsAPI | `{date}/ProductsAPI/` | Web_Logs |
| SalesChannelsAPI | `{date}/SalesChannelsAPI/` | Web_Logs |
| SendGridWebhookApi | `{date}/SendGridWebhookApi/` | Web_Logs |
| ShippingAPI | `{date}/ShippingAPI/` | Web_Logs |
| WebServices | `{date}/WebServices/` | Web_Logs |
| WebSite | `{date}/WebSite/` | Web_Logs |

### Frontend Services (also in web-logs or openretail)

- SC.Base.API.FrontEnd.General
- SC.Base.FrontEnd.Core
- SC.Internal.FrontEnd.Core
- SC.Internal.API.DevOps
- Integrations.IntegrationPortal
- SC.System.FrontEnd.*

---

## Category F: Legacy (DB Logging)

**Route:** SQL `appslogs` table → Blob `services-logs`

| Service | SQL Table | Notes |
|---------|-----------|-------|
| GrouponOrdersSync | appslogs (via Logs table) | Groupon orders |
| GrouponTrackingSync | appslogs (via Logs table) | Groupon tracking |
| SPSCommerce | appslogs (via ActivityLogger) | SPS Commerce EDI |

---

## Category G: Messaging & AI

**Route:** Blob `openretail` (applogs) + CosmosDB (operational data)

| Service | Blob Container | Notes |
|---------|---------------|-------|
| SC.System.Marketplaces.eBay.MessagingApp | openretail/applogs | eBay messaging |
| SC.System.Marketplaces.Messaging.Autoreply | openretail/applogs | Auto-reply messaging |
| AI.AutoReplyAgent | openretail/applogs | AI auto-reply agent |
| SC.System.AI.* | openretail/applogs | AI services |

Note: CosmosDB operational data is handled by the separate `cosmos_db` skill, not this skill.

---

## Blob Container Service Lists

### openretail Container (verified services, lowercase)

```
lds_bigcommerceorderssync, lds_searsproductlister
```
(More services being migrated — list grows over time. Use blob prefix listing to discover current services.)

### Routing Priority

1. **SMB network share** — For real-time data (< 4 hours old)
2. **Azure Blob Storage** — Primary historical source
3. **SQL Server** — Secondary, for structured CompanyId/ApplicationId queries

### Sub-Service Dependencies

| When investigating... | Also check... |
|----------------------|---------------|
| Any *OrdersSync | SC.Marketplace.Engine.OrderImport |
| Any *QtySync | SC.Marketplace.Engine.InventorySync |
| Any *ProductLister | SC.Marketplace.Engine.Listing |
| Any *Repricer | SC.Marketplace.Engine.PriceSync |
| Any *ShipmentSync | SC.Marketplace.Engine.ShipmentUpdate |
| Shopify orders | SC.System.Carts.Shopify + SC.Marketplace.Engine.OrderImport |
| BigCommerce orders | LDS_BigCommerceOrdersSync + SC.Marketplace.Engine.OrderImport |
| Web API issues | Corresponding marketplace engine services |
