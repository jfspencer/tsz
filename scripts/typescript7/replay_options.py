"""Translate native option values using the pinned compiler's own declarations."""


class UnsupportedReplay(ValueError):
    """An adapter limitation, never a candidate pass or compiler diagnosis."""


def option_value(value, schema):
    kind = schema["kind"]
    if kind == "enum":
        for name, native in sorted(schema["enum"].items()):
            if type(value) is type(native) and value == native:
                return name
    elif kind == "boolean" and type(value) is bool:
        return "true" if value else "false"
    elif kind == "string" and isinstance(value, str):
        return value
    elif kind == "number" and type(value) in (int, float):
        return str(value)
    elif kind in ("list", "listOrElement") and isinstance(value, list):
        items = [option_value(item, schema["element"]) for item in value]
        if any("," in item for item in items):
            raise UnsupportedReplay("a list element contains the CLI separator")
        return ",".join(items)
    raise UnsupportedReplay(f"unrepresentable {schema['name']} value: {value!r}")


def command_line(record, schema):
    # This native call creates the original fixture compilation. Auxiliary
    # calls can compile oracle-generated declarations and must not be replayed
    # as source fixtures. Their eventual adapter must use TSZ intermediates.
    if "github.com/microsoft/typescript-go/internal/testrunner.newCompilerTest" not in record.get("callers", []):
        raise UnsupportedReplay("auxiliary or unidentified native driver requires its own replay")
    if record.get("config_source") is not None:
        raise UnsupportedReplay("native parsed-config provenance requires the project adapter")
    if not record["native_harness_options"]["UseCaseSensitiveFileNames"]:
        raise UnsupportedReplay("case-insensitive virtual filesystem is not implemented")
    if record["native_harness_options"].get("CaptureSuggestions"):
        raise UnsupportedReplay("suggestion diagnostics require the service adapter")
    roots = record["roots"]
    if not roots:
        raise UnsupportedReplay("an empty native root set cannot be represented by the CLI")
    args = ["--ignoreConfig"]
    for name, value in sorted(record["native_compiler_options"].items()):
        option = schema.get(name)
        if option is None or option["config_only"]:
            raise UnsupportedReplay(f"native option requires a non-CLI adapter: {name}")
        args.extend(["--" + option["name"], option_value(value, option)])
    # Preserve root order and authored source bytes. Absolute paths resolve in
    # the mounted virtual root, not in a renamed source tree.
    return args + roots
