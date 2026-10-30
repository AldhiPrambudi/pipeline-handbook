"""Small fail-closed validator for the documented JSON Schema subset we use.

No remote references, extension keywords or executable rule expressions.
"""
import re


def validate(value, schema, path="$", root=None):
    root = root or schema
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            raise ValueError("only local schema references supported")
        target = root
        for part in ref[2:].split("/"):
            target = target[part]
        return validate(value, target, path, root)
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool,
             "integer": int, "number": (int, float), "null": type(None)}
    kind = schema.get("type")
    if kind and (not isinstance(value, kinds[kind]) or kind in ("integer", "number") and isinstance(value, bool)):
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: value is outside allowed choices")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}", root)
            elif schema.get("additionalProperties", True) is False:
                raise ValueError(f"{path}: unexpected property {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(item, schema["additionalProperties"], f"{path}.{key}", root)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 1000000):
            raise ValueError(f"{path}: array size exceeds bounds")
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]", root)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1000000):
            raise ValueError(f"{path}: string length exceeds bounds")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path}: invalid format")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ValueError(f"{path}: number exceeds bounds")
