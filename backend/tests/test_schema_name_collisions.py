"""No two response models may share a class name across schema modules.

FastAPI derives an OpenAPI component name from the class name. When two
classes collide it falls back to module-qualified names like
app__schemas__mosaic__StatusResponse for some of them and leaves the plain
name on one, which then reads as the canonical type in the generated client
while being nothing of the sort. Three classes named StatusResponse produced
exactly that.
"""
import importlib
import pkgutil

from pydantic import BaseModel


def _all_schema_models():
    import app.schemas as schemas_pkg

    seen: dict[str, list[str]] = {}
    for module_info in pkgutil.iter_modules(schemas_pkg.__path__):
        module = importlib.import_module(f"app.schemas.{module_info.name}")
        for attr in dir(module):
            value = getattr(module, attr)
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value.__module__ == module.__name__
            ):
                seen.setdefault(attr, []).append(module.__name__)
    return seen


def test_no_response_model_class_name_is_declared_twice():
    duplicates = {
        name: modules
        for name, modules in _all_schema_models().items()
        if len(modules) > 1
    }
    assert not duplicates, f"colliding schema class names: {duplicates}"


def test_the_generic_status_response_keeps_the_plain_name():
    from app.schemas.common import StatusResponse
    from app.schemas.mosaic import MosaicStatusResponse
    from app.schemas.target import TargetStatusResponse

    assert StatusResponse.model_fields.keys() == {"status"}
    assert MosaicStatusResponse.model_fields.keys() == {"status"}
    assert TargetStatusResponse.model_fields.keys() == {"status"}
