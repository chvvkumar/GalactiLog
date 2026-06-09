from pydantic import BaseModel


class BootstrapUser(BaseModel):
    id: str
    username: str
    role: str


class BootstrapEquipmentItem(BaseModel):
    name: str
    grouped: bool


class BootstrapEquipment(BaseModel):
    cameras: list[BootstrapEquipmentItem]
    telescopes: list[BootstrapEquipmentItem]


class BootstrapObjectType(BaseModel):
    object_type: str
    count: int


class BootstrapCustomColumn(BaseModel):
    id: str
    name: str
    slug: str
    column_type: str
    applies_to: str
    dropdown_options: list | None = None
    display_order: int | None = None
    created_by: str
    created_at: str | None = None


class BootstrapResponse(BaseModel):
    user: BootstrapUser
    settings: dict
    equipment: BootstrapEquipment
    fits_keys: list[str]
    object_types: list[BootstrapObjectType]
    custom_columns: list[BootstrapCustomColumn]
