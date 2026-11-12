Diskussion 11.11.2026
---------------------

- Konfig Format unverändert (inkl Facadekinder, bei Parents hide_sublayers=true)
  * Frage: Wie soll `qwc-config-generator` künftig Facadeebenen konfigurieren? GetProjectSettings liefert keine Attribute für Facadelayer

- Mockup Template-Designer:

    ```
    |-----------------------------------------|-----------------------------------------------|
    | Coordinate: [        ]    Layer: [              ]       Info type: [wms|sql] [parameter]|
    |-----------------------------------------|-----------------------------------------------|
    | attributes: [....]                      |  Template parameters | Output | Help          |
    |                                         |-----------------------------------------------|
    |                                         |                                               |
    |                                         |                                               |
    |                                         |                                               |
    |                                         |                                               |
    |                                         |                                               |
    |                                         |                                               |
    |-----------------------------------------|-----------------------------------------------|
    ```

- Frage: QGIS Server -> OGC Service auf JSON umstellen?
  * Vorteil: JSON erlaubt das Unterscheiden zumindest zwischen `bool`, `number`, `string` und `null`

# Attributkonfiguration

*Schema:*

```json
  "attributes": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "name": {"description": "Attribute name", "type": "string"},
        "alias": {"description": "Attribute alias", "type": "string"},
        "format": {"description": "Formatting expression", "type": "string"},
        "format_base64": {"description": "Formatting expression, base64 encoded", "type": "string"},
        "tempate": {"description": "Value JINJA template", "type": "string"},
        "alias_template": {"description": "Alias JINJA template", "type": "string"},
        "json_attributes": {
          "title": "JSON attribute formats",
          "description": "Formats for attributes in JSON values",
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {"description": "Attribute name in JSON value", "type": "string"},
              "alias": {"description": "Alias for attribute in JSON value", "type": "string"},
              "format": {"description": "Formatting expression", "type": "string"},
              "format_base64": {"description": "Formatting expression, base64 encoded", "type": "string"},
              "tempate": {"description": "Value JINJA template", "type": "string"},
              "alias_template": {"description": "Alias JINJA template", "type": "string"},
            },
            "required": ["name", "alias"],
            "additionalProperties": false
          }
        }
      },
      "required": ["name", "alias"],
      "additionalProperties": false
    }
  }
```

## Einfach

*Data*:

```json
{
  "<Name>": "<Value>"
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>"
  }
]

```

*Output*:

```
|-----------|---------|
| <Alias>   | <Value> |
|-----------|---------|
```

## JSON Listen-Attribut

*Data*:

```json
{
  "<Name>": ["<Value1>", "<Value2>", ...]
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>"
  }
]
```

*Output*:

```
|-----------|------------|
| `<Alias>` | `<Value1>` |
|           | `<Value2>` |
|-----------|------------|
```

## JSON Objekt-Attribut

*Data*:

```json
{
  "<Name>": {"<Key1>": "<Value1>", "<Key2>": "<Value2>", ...}
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>",
    "json_attributes": [
      {"name": "<Key1>", "alias": "<Alias1>"},
      {"name": "<Key2>", "alias": "<Alias2>"}
      ...
    ]
  }
]
```

*Output*:

```
|-----------|----------|----------|
| <Alias>   | <Alias1> | <Value1> |
|           |----------|----------|
|           | <Alias2> | <Value2> |
|-----------|----------|----------|
```

## JSON Objektliste-Attribut

*Data*:

```json
{
  "<Name>": [{"<Key1>": "<Value11>", "<Key2>": "<Value12>", ...}, {"<Key1>": "<Value21>", "<Key2>": "<Value22>", ...}, ...]
}

```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>",
    "json_attributes": [
      {"name": "<Key1>", "alias": "<Alias1>"},
      {"name": "<Key2>", "alias": "<Alias2>"}
      ...
    ]
  }
]
```

*Output*:

```
|-----------|----------|-----------|
| <Alias>   | <Alias1> | <Value11> |
|           |----------|-----------|
|           | <Alias2> | <Value12> |
|           |==========|===========|
|           | <Alias1> | <Value21> |
|           |----------|-----------|
|           | <Alias2> | <Value22> |
|-----------|----------|-----------|
```

## Promoted-Attribute

*Data*:

```json
{
  "<Name>": "<Value>"
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": ""
  }
]
```

*Output*:

```
|-----------|---------|
|<Value>              |
|-----------|---------|
```

## Virtuelles-Attribute

*Data*:

```json
{
  "<Name>": "<Value>"
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>"
  },
  {
    "name": "<OtherName>",      # Technischer name für Berechtigungen
    "alias": "<OtherAlias>",
    "template": "<Template>"    # Erforderlich für virtuelle Attribute
  }
]
```

*Output*:

```
|--------------|--------------------|
| <Alias>      | <Value>            |
|--------------|--------------------|
| <OtherAlias> | render(<Template>) |
|--------------|--------------------|
```

## Überschriftsattribut

*Data*:

```json
{
  "<Name>": "<Value>"
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name>",
    "alias": "<Alias>"
  },
  {
    "name": "<OtherName>",      # Irgendwas, eigentlich unnötig
    "alias": "<Title>",
    "template": ""              # Template leer
  }
]
```

*Output*:

```
|--------------|--------------------|
| <Alias>      | <Value>            |
|--------------|--------------------|
| <Title>                           |
|--------------|--------------------|
```

## Attribut unterdrücken

*Data*:

```json
{
  "<Name1>": "<Value1>",
  "<Name2>": "<Value2>"
}
```

*Config*:

```json
"attributes": [
  {
    "name": "<Name1>",
    "alias": "<Alias1>"
  },
  {
    "name": "<Name2>",
    "alias": "",                # Alias leer
    "template": ""              # Template leer
  }
]
```

*Output*:

```
|--------------|--------------------|
| <Alias1>     | <Value1>           |
|--------------|--------------------|
```

## Formattierung ohne Template

Sowohl für top-level Attribute als für JSON-Attribute sind ohne Verwendung von `template` folgende Attributwertformattierungen möglich:

- *Datumsformattierun*: Folgende Konversionen werden automatisch angewendet

    ```
    "%Y-%m-%dT%H:%M:%S.%f" => "%d.%m.%Y %H:%M:%S"
    "%Y-%m-%dT%H:%M:%S" => "%d.%m.%Y %H:%M:%S"
    "%Y-%m-%d" => "%d.%m.%Y"
    ```

  Diese Regeln sind konfigurierbar (via `date_conversion_rules`).
- Zahlen können via `format` mit hilfe der [Python format language](https://docs.python.org/3/library/string.html#format-specification-mini-language) formattiert werden:

    ```json
    "attributes": [
      {"name": "num", "alias": "Number", "format": " >+10.3f"}
      ...
    ]
    ```

- Attributerte können mit einem Lookup-Dictionary transformiert werden:

    ```json
    "attributes": [
      {"name": "bool", "alias": "Boolean", "format": '{"0": "False", "1": "True"}'}
      ...
    ]
    ```

## Formattierung mit Template

Sowohl für top-level Attribute als für JSON-Attribute können Attributwerte mit `template` und Aliases mit `alias_template` mit JINJA templates frei formattiert werden.

Dem Template steht jeweils das komplette Feature zur Verfügung. Damit sind z.B. auch kombinierte Attribute möglich:

```json
  "attributes": [
    {"name": "address", "alias": "Adresse", "template": "{{ feature.street }} {{ feature.housenr }}, {{ feature.city }}"}
      ...
  ]
```

Im Zusammenhang mit kombinierte Attribute ist auch das Unterdücken von Attribute relevant, siehe oben.
