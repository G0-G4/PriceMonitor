from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class WbSize(BaseModel):
    sizeID: int
    price: float | None = None
    discountedPrice: float | None = None
    clubDiscountedPrice: float | None = None
    techSizeName: str | None = None


class WbGoods(BaseModel):
    model_config = ConfigDict(extra="ignore")
    nmID: int
    vendorCode: str | None = None
    sizes: list[WbSize] = Field(default_factory=list)
    currencyIsoCode4217: str | None = None
    discount: int | None = None
    clubDiscount: int | None = None
    editableSizePrice: bool | None = None


class WbListGoodsData(BaseModel):
    listGoods: list[WbGoods] = Field(default_factory=list)


class WbListGoodsResponse(BaseModel):
    data: WbListGoodsData | None = None
    error: bool = False
    errorText: str | None = None


class WbPriceChange(BaseModel):
    date: date
    account: str
    nm_id: int
    vendor_code: str | None
    name: str | None
    tech_size_name: str | None
    today_seller_price: float | None
    today_spp: float | None
    today_wallet: float | None
    yesterday_seller_price: float | None
    yesterday_spp: float | None
    yesterday_wallet: float | None


class WbPriceChangeResponse(BaseModel):
    price_changes: list[WbPriceChange]
    total: int
