from collections import OrderedDict
from datetime import datetime
from xml.dom.minidom import parseString
from jinja2 import Template

import argparse
import json
import os
import base64
import html
import uuid
import re
import requests
import jsonschema
import logging


class Logger():
    """Simple logger class"""

    def __init__(self, logger_name, logging_level):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging_level)

        stream_handler = logging.StreamHandler()
        # \x1b[0m resets the color to default
        stream_handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] %(color)s %(levelname)s: %(message)s \x1b[0m"))

        self.logger.addHandler(stream_handler)

    def debug(self, msg):
        self.logger.debug(msg, extra={'color': "\033[36m"})

    def info(self, msg):
        self.logger.info(msg, extra={'color': ""})

    def warning(self, msg):
        self.logger.warning(msg, extra={'color': "\033[33m"})

    def error(self, msg):
        self.logger.error(msg, extra={'color': "\033[31m"})

    def timestamp(self):
        return datetime.now()


class Json2Qgs():
    """Json2Qgs class

    Generate QGS and QML files from a JSON config file.
    """

    # default extent for WMS and layers if not set in config
    DEFAULT_EXTENT = [2590983, 1212806, 2646267, 1262755]

    def __init__(self, config, logger, dest_path, qgis_version,
                 qgs_template_dir, qgs_name):
        """Constructor

        :param obj config: Json2Qgs config
        :param Logger logger: Logger
        :param str dest_path: Path where the generated files should be saved
        :param str qgis_version: Define the version of the QGIS template to use
        :param str qgs_template_dir: Path to the qgs template dir where the
                   default QMLs and QGIS template files should exist
        :param str qgs_name: Target base name of generated QGS files
        """
        self.logger = logger

        self.config = config
        self.can_generate = True

        self.project_output_dir = os.path.abspath(dest_path)
        qgs_template_dir = os.path.abspath(qgs_template_dir)

        # get config settings

        # default extent
        if 'wms_metadata' in config:
            self.default_extent = config.get('wms_metadata', {}) \
                .get("bbox", {}).get("bounds", self.DEFAULT_EXTENT)
        elif 'wfs_metadata' in config:
            self.default_extent = config.get('wfs_metadata', {}) \
                .get("bbox", {}).get("bounds", self.DEFAULT_EXTENT)
        else:
            self.default_extent = self.DEFAULT_EXTENT

        self.selection_color = config.get(
            'selection_color_rgba', [255, 255, 0, 255]
        )

        if qgis_version == '3':
            self.qgs_template_fn = os.path.join(
                qgs_template_dir, 'service_3.qgs')
        else:
            self.qgs_template_fn = os.path.join(
                qgs_template_dir, 'service_2.qgs')

        if not os.path.exists(self.qgs_template_fn):
            self.can_generate = False
            self.logger.error(
                "Could not find QGIS template file under: %s" % (
                    self.qgs_template_fn))

        # load default styles
        self.default_styles = {
            "point": self.load_template(
                os.path.join(qgs_template_dir, 'point.qml')),
            "linestring": self.load_template(
                os.path.join(qgs_template_dir, 'linestring.qml')),
            "polygon": self.load_template(
                os.path.join(qgs_template_dir, 'polygon.qml')),
            "raster": self.load_template(
                os.path.join(qgs_template_dir, 'raster.qml'))
        }

        self.qgs_name = qgs_name

        self.wms_top_layers = config.get("wms_top_layers", [])

    def load_template(self, path):
        """Load contents of QGIS template file.

        :param str path: Path to template file
        """
        template = None
        try:
            with open(path) as f:
                template = f.read()
        except Exception as e:
            self.can_generate = False
            self.logger.error("Error loading template file '%s':\n%s" % (path, e))

        return template

    def parse_qml_style(self, xml, attributes=[]):
        """ Parse QML and set aliases
        """
        doc = parseString(xml)
        qgis = doc.getElementsByTagName("qgis")[0]
        attr = " ".join(['%s="%s"' % entry for entry in filter(
            lambda entry: entry[0] != "version", qgis.attributes.items())])

        # update aliases
        if attributes:
            aliases = qgis.getElementsByTagName("aliases")
            if not aliases:
                # create <aliases>
                aliases = doc.createElement("aliases")
            else:
                # get <aliases>
                aliases = aliases[0]

            # remove existing aliases
            for alias in list(aliases.childNodes):
                aliases.removeChild(alias)

            # add aliases from layer config
            for i, attribute in enumerate(attributes):
                # get alias from from alias data
                self.logger.debug("alias %s" % attribute.get("alias"))
                attr_alias = attribute.get("alias", "")
                try:
                    if attr_alias.startswith('{'):
                        # parse JSON
                        json_config = json.loads(attr_alias)
                        attr_alias = json_config.get('alias', attr_alias)
                except Exception as e:
                    self.logger.warning(
                        "Could not parse value as JSON: '%s'\n%s" %
                        (attr_alias, e)
                    )

                alias = doc.createElement("alias")
                alias.setAttribute('field', attribute["name"])
                alias.setAttribute('index', str(i))
                alias.setAttribute('name', attr_alias)
                aliases.appendChild(alias)

        style = "".join([node.toxml() for node in qgis.childNodes])
        return {"attr": attr, "style": style}

    def path_is_child(self, parent_path, child_path):
        """Checks wheter child_path is a subdir in parent_path

        param str parent_path :  Parent path
        param str child_path : Child path
        return bool : True if child is a subdir of parent
        """
        parent_path = os.path.abspath(parent_path)
        child_path = os.path.abspath(child_path)

        return os.path.commonpath([parent_path]) == os.path.commonpath(
            [parent_path, child_path])

    def collect_nested_layer(self, layer_name, layers_lookup, depth=0):
        """Recursively collect layer infos for layersubtree from qgsContent.

        NOTE: only used for WMS mode

        :param str layer_name: Layer name
        :param dict layers_lookup: Lookup for layer configs by name
        :param int depth: Depth of recursion for log formatting
        """
        layer_info = None

        layer = layers_lookup.get(layer_name)
        self.logger.debug("layer %s" % layer)
        if layer is None:
            self.logger.warning(
                "Could not find layer %s'%s'" % ("  " * depth, layer_name)
            )
            return layer_info

        # NOTE: log output aligned to warning above
        self.logger.debug(
            "Adding layer:          %s'%s'" % ("  " * depth, layer["name"])
        )

        if layer.get("type") == 'productset':
            # group layer

            # collect sublayers
            sublayers = []
            for sublayer in layer["sublayers"]:
                sublayer_info = self.collect_nested_layer(
                    sublayer, layers_lookup, depth + 1
                )
                if sublayer_info:
                    sublayers.append(sublayer_info)

            layer_info = {
                "type": layer["type"],
                "name": layer["name"],
                "title": layer["title"],
                "items": sublayers
            }
        else:
            # single layer
            layer_info = self.collect_single_layer(layer, True)

        return layer_info

    def collect_single_layer(self, layer, is_wms):
        """Collect single layer info for layersubtree from qgsContent.

        :param dict layer: Data layer dictionary
        :param bool is_wms: Whether mode is WMS or WFS
        """

        layer_keys = layer.keys()
        qgs_layer = {
            "type": "layer",
            "name": html.escape(layer["name"]),
            "title": html.escape(layer["title"]),
            "id": str(uuid.uuid4()),
            "mapTip": "",
            "dataUrl": "",
            "abstract": "",
            }

        if "bbox" in layer_keys:
            qgs_layer["extent"] = layer["bbox"]["bounds"]
        else:
            qgs_layer["extent"] = self.default_extent

        if "postgis_datasource" in layer_keys:
            # datasource from the JSON config
            datasource = layer["postgis_datasource"]
            qgs_layer["layertype"] = "vector"
            qgs_layer["provider"] = "postgres"
            qgs_layer["datasource"] = (
                "{db_connection} sslmode=disable key='{pkey}' srid={srid} "
                "type={geometry_type} table=\"{schema}\".\"{table}\" "
                "({geometry_column}) sql=".format(
                    db_connection=datasource["dbconnection"],
                    pkey=datasource["unique_key"],
                    srid=datasource["srid"],
                    geometry_type=datasource["geometry_type"],
                    schema=datasource["schema"],
                    table=datasource["table"],
                    geometry_column=datasource["geometry_field"]
                    )
                )
            try:
                self.logger.debug("attributes %s" % layer.get("attributes",[]))
                qml = self.get_qml_from_base64(
                    layer["qml_base64"], layer.get("attributes", []))
                qgs_layer["style"] = qml["style"]
                qgs_layer["attributes"] = qml["attr"]
                #self.logger.debug("qml %s" % qml["style"])

            except:
                if is_wms:
                    self.logger.warning(
                        "Falling back to default style for %s" % layer["name"])

                singletype = re.sub(
                    '^multi', "", datasource["geometry_type"].lower())
                qml = self.parse_qml_style(
                    self.default_styles[singletype],
                    layer.get("attributes", []))
                qgs_layer["style"] = qml["style"]
                qgs_layer["attributes"] = qml["attr"]

            if "dimension" in layer_keys:
                qgs_layer["wmsDimensions"] = "<dimension defaultDisplayType='0' fieldName='schadendatum' unitSymbol='' units='ISO8601' name='time' referenceValue='' endFieldName='enddatum'/>"
            if "qml_assets" in layer_keys:
                # Iterate through all assets used in the QML and save them
                # in the filesystem
                # If the asset path defines directories that do not exist,
                # then create those directories and save the asset image
                for asset in layer["qml_assets"]:
                    try:
                        # save asset in additional subdir named after layer
                        # i.e. <project_output_dir>/<layer name>/<asset path>
                        rel_asset_path = os.path.join(
                            layer["name"], asset["path"]
                        )
                        asset_path = os.path.join(
                            self.project_output_dir, rel_asset_path
                        )
                        if self.path_is_child(self.project_output_dir, asset_path):
                            os.makedirs(
                                os.path.dirname(asset_path), exist_ok=True)
                            with open(asset_path, "wb") as fh:
                                fh.write(
                                    base64.b64decode(asset["base64"]))

                            # update relative symbol paths in QML
                            pattern = "v=\"%s\"" % asset["path"]
                            replacement = "v=\"%s\"" % rel_asset_path
                            qgs_layer["style"] = qgs_layer["style"].replace(
                                pattern, replacement
                            )
                        else:
                            self.logger.warning(
                                "[Layer: {}] An error occured when trying "
                                "to save {}\nAssets can only be"
                                " saved under {}!".format(
                                    qgs_layer["name"], asset["path"],
                                    self.project_output_dir))
                    except Exception as e:
                        self.logger.warning(
                            "[Layer: {}] An error occured when trying to save {}\n{}".format(
                                qgs_layer["name"], asset["path"], str(e)))

        elif "raster_datasource" in layer_keys:
            # TODO: srid is not used here?
            # datasource from the JSON config
            qgs_layer["provider"] = "gdal"
            qgs_layer["layertype"] = "raster"
            qgs_layer["datasource"] = layer["raster_datasource"]["datasource"]

            try:
                qml = self.get_qml_from_base64(
                    layer["qml_base64"], layer.get("attributes", []))
                qgs_layer["style"] = qml["style"]
                qgs_layer["attributes"] = qml["attr"]

            except:
                self.logger.warning(
                    "Falling back to default style for %s" % layer["name"])

                qml = self.parse_qml_style(
                    self.default_styles["raster"],
                    layer.get("attributes", []))
                qgs_layer["style"] = qml["style"]
                qgs_layer["attributes"] = qml["attr"]

        elif "wms_datasource" in layer_keys:
            # Constant value
            datasource = html.escape("contextualWMSLegend=0&")
            datasource += html.escape(
                "crs=EPSG:%s&" % layer["wms_datasource"]["srid"])
            # Constant value
            datasource += html.escape("dpiMode=7&")
            datasource += html.escape(
                "featureCount=%s&" % layer["wms_datasource"].get(
                    "featureCount", 10))
            datasource += html.escape(
                "format=%s&" % layer["wms_datasource"]["format"])
            datasource += html.escape(
                "layers=%s&" % layer["wms_datasource"]["layers"])
            datasource += html.escape(
                "styles=%s&" % layer["wms_datasource"].get(
                    "styles", self.default_styles["raster"]))
            datasource += html.escape(
                "url=%s" % layer["wms_datasource"]["wms_url"])

            qgs_layer["provider"] = "wms"
            qgs_layer["datasource"] = datasource
            qgs_layer["layertype"] = "raster"
        elif "wmts_datasource" in layer_keys:
            # Constant value
            datasource = html.escape("contextualWMSLegend=0&")
            datasource += html.escape(
                "crs=EPSG:%s&" % layer["wmts_datasource"]["srid"])
            # Constant value
            datasource += html.escape("dpiMode=7&")
            # Constant value
            datasource += html.escape("featureCount=10&")
            datasource += html.escape(
                "format=%s&" % layer["wmts_datasource"]["format"])
            datasource += html.escape(
                "layers=%s&" % layer["wmts_datasource"]["layer"])
            datasource += html.escape(
                "styles=%s&" % layer["wmts_datasource"].get(
                    "style", self.default_styles["raster"]))
            datasource += html.escape(
                "tileDimensions=%s&" % layer["wmts_datasource"].get(
                    "tile_dimensions", ""))
            datasource += html.escape(
                "tileMatrixSet=%s&" % layer["wmts_datasource"][
                    "tile_matrix_set"])
            datasource += html.escape(
                "url=%s" % layer["wmts_datasource"]["wmts_capabilities_url"])

            qgs_layer["provider"] = "wms"
            qgs_layer["datasource"] = datasource
            qgs_layer["layertype"] = "raster"

        return qgs_layer

    def get_qml_from_base64(self, base64_qml, attributes):
        """Decode base64_qml with base64 and return the parsed qml style

        param str base64_qml: QML encoded with base64
        param list attributes: attributes list used to set aliases in the QML
        return dict {"attr": data, "style": data}
        """

        qml = base64.b64decode(base64_qml).decode("utf-8")
        return self.parse_qml_style(qml, attributes)

    def collect_wms_metadata(self, metadata, layertree, composers=[]):
        """Collect wms metadata from qgsContent

        param dict metadata: Metadata specified in qgsContent
        param list layertree: The whole QGS layer tree
        return dict bindings: Dict for jinja
        """
        # TODO: Where do we use this?
        wms_service_name = metadata.get('service_name') or ''
        wms_online_resource = metadata.get('online_resource') or ''

        wms_extent = metadata.get('bbox')
        if wms_extent:
            wms_extent = wms_extent['bounds']

        return {
                'wms_service_title': html.escape(
                    metadata.get('service_title') or ''),
                'wms_service_abstract': html.escape(
                    metadata.get('service_abstract') or ''),
                'wms_keywords': metadata.get('keywords', None),
                'wms_url': html.escape(wms_online_resource),
                'wms_contact_person': html.escape(
                    metadata.get('contact_person') or ''),
                'wms_contact_organization': html.escape(
                    metadata.get('contact_organization') or ''
                ),
                'wms_contact_position': html.escape(
                    metadata.get('contact_position') or ''),
                'wms_contact_phone': html.escape(
                    metadata.get('contact_phone') or ''),
                'wms_contact_mail': html.escape(
                    metadata.get('contact_mail') or ''),
                'wms_fees': html.escape(metadata.get('fees') or ''),
                'wms_access_constraints': html.escape(
                    metadata.get('access_constraints') or ''),
                'wms_root_name': html.escape(
                    metadata.get('root_name') or ''),
                'wms_root_title': html.escape(
                    metadata.get('root_title') or ''),
                'wms_crs_list': metadata.get('crs_list') or ['EPSG:2056'],
                'wms_extent': wms_extent,
                'wms_max_width': self.config.get('wms_max_width'),
                'wms_max_height': self.config.get('wms_max_height'),
                'layertree': layertree,
                'composers': composers,
                'selection_color': self.selection_color
            }

    def collect_wfs_metadata(self, metadata, layertree):
        """Collect wfs metadata from qgsContent

        param dict metadata: Metadata specified in qgsContent
        param list layertree: The whole QGS layer tree
        """
        # TODO: Where do we use this?
        wfs_service_name = metadata.get('service_name') or ''
        wfs_online_resource = metadata.get('online_resource') or ''

        layer_ids = []

        for layer in layertree:
            layer_ids.append(layer["id"])

        return {
                'wms_service_title': html.escape(
                    metadata.get('service_title') or ''),
                'wms_service_abstract': html.escape(
                    metadata.get('service_abstract') or ''),
                'wms_keywords': metadata.get('keywords', None),
                'wms_fees': html.escape(metadata.get('fees') or ''),
                'wms_access_constraints': html.escape(
                    metadata.get('access_constraints') or ''),
                'wfs_url': html.escape(wfs_online_resource),
                'layertree': layertree,
                'wfs_layers': layer_ids,
                'composers': [],
                'selection_color': self.selection_color
            }

    def generate_wms_project(self):
        """Generate project

        param bool with_composers: Wether to add the defined
                                   composers to the project
        """

        if os.path.exists(self.project_output_dir) is False:
            self.logger.error(
                "Destination directory ({}) does not exist!".format(
                    self.project_output_dir))
            return

        if self.validate_schema() is False:
            return

        qgis_template = self.load_template(self.qgs_template_fn)

        # collect lookup for layers by name
        layers_lookup = {}
        for layer in self.config.get("layers"):
            layers_lookup[layer["name"]] = layer

        composers = []
        layertree = []

        for layer_name in self.wms_top_layers:
            layer_info = self.collect_nested_layer(layer_name, layers_lookup)
            if layer_info:
                layertree.append(layer_info)

        # Iterate through all assets used in the QPT and save them
        # in the filesystem
        # If the asset path defines directories that do not exist,
        # then create those directories and save the asset image
        for composer in self.config.get("print_templates", []):
            try:
                composers.append(base64.b64decode(
                    composer["template_base64"]).decode("utf-8"))

            except:
                self.logger.error(
                    "Error trying to decode print template!")

            for asset in composer.get("template_assets", []):
                try:
                    asset_path = os.path.join(
                        self.project_output_dir, asset["path"]
                    )
                    if self.path_is_child(self.project_output_dir, asset_path):
                        os.makedirs(
                            os.path.dirname(asset_path), exist_ok=True)
                        with open(asset_path, "wb") as fh:
                            fh.write(
                                base64.b64decode(asset["base64"]))
                    else:
                        self.logger.warning(
                            "An error occured when trying to save {}\n"
                            "Assets can only be"
                            " saved under {}".format(
                                asset["path"], self.project_output_dir))
                except Exception as e:
                    self.logger.warning(
                        "An error occured when trying to save {}\n{}".format(
                            asset["path"], str(e)))

        qgs_template = Template(qgis_template)
        binding = self.collect_wms_metadata(self.config.get(
            "wms_metadata", {}), layertree, composers=composers)
        qgs = qgs_template.render(**binding)

        qgs_filename = "%s.qgs" % self.qgs_name
        qgs_path = os.path.join(self.project_output_dir, qgs_filename)

        try:
            with open(qgs_path, 'w', encoding='utf-8') as f:
                f.write(qgs)
                self.logger.debug("Wrote %s" % os.path.abspath(qgs_path))
        except PermissionError:
            self.logger.error(
                "PermissionError: Could not write %s" % os.path.abspath(
                    qgs_path))

    def generate_wfs_project(self):
        """Generate WFS project

        """

        if os.path.exists(self.project_output_dir) is False:
            self.logger.error(
                "Destination directory ({}) does not exist!".format(
                    self.project_output_dir))
            return

        if self.validate_schema() is False:
            return

        qgis_template = self.load_template(self.qgs_template_fn)
        layers = self.config.get("layers")

        composers = []
        layertree = []

        for layer in layers:
            self.logger.debug("Adding layer:'%s'" % layer["name"])
            layertree.append(self.collect_single_layer(layer, False))

        qgs_template = Template(qgis_template)
        binding = self.collect_wfs_metadata(self.config.get(
            "wfs_metadata", {}), layertree)
        qgs = qgs_template.render(**binding)

        qgs_filename = "%s.qgs" % self.qgs_name
        qgs_path = os.path.join(self.project_output_dir, qgs_filename)

        try:
            with open(qgs_path, 'w', encoding='utf-8') as f:
                f.write(qgs)
                self.logger.debug("Wrote %s" % os.path.abspath(qgs_path))
        except PermissionError:
            self.logger.error(
                "PermissionError: Could not write %s" % os.path.abspath(
                    qgs_path))

    def validate_schema(self):
        """Validate config against its JSON schema.

        return bool valid : Return true if JSON config is valid
        """

        # download JSON schema
        response = requests.get(self.config["$schema"])
        if response.status_code != requests.codes.ok:
            self.logger.error(
                "Could not download JSON schema from %s:\n%s" %
                (self.config["$schema"], response.text)
            )
            return False

        # parse JSON
        try:
            schema = json.loads(response.text)
        except Exception as e:
            self.logger.error("Could not parse JSON schema:\n%s" % e)
            return False

        # validate against schema
        valid = True
        validator = jsonschema.validators.validator_for(schema)(schema)
        for error in validator.iter_errors(self.config):
            valid = False

            # collect error messages
            messages = [
                e.message for e in error.context
            ]
            if not messages:
                messages = [error.message]

            # collect path to concerned subconfig
            # e.g. ['resources', 'wms_services', 0]
            #      => ".resources.wms_services[0]"
            path = ""
            for p in error.absolute_path:
                if isinstance(p, int):
                    path += "[%d]" % p
                else:
                    path += ".%s" % p

            # get concerned subconfig
            instance = error.instance
            if isinstance(error.instance, dict):
                # get first level of properties of concerned subconfig
                instance = OrderedDict()
                for key, value in error.instance.items():
                    if isinstance(value, dict) and value.keys():
                        first_value_key = list(value.keys())[0]
                        instance[key] = {
                            first_value_key: '...'
                        }
                    elif isinstance(value, list):
                        instance[key] = ['...']
                    else:
                        instance[key] = value

            # log errors
            message = ""
            if len(messages) == 1:
                message = "Validation error: %s" % messages[0]
            else:
                message = "\nValidation errors:\n"
                for msg in messages:
                    message += "  * %s\n" % msg
            self.logger.error(message)
            self.logger.warning("Location: %s" % path)
            self.logger.warning(
                "Value: %s" %
                json.dumps(
                    instance, sort_keys=False, indent=2, ensure_ascii=False
                )
            )
        return valid


# command line interface
if __name__ == '__main__':
    print("Starting SO!GIS json2qgs...")

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'qgsContent', help="Path to qgsContent config file"
    )
    parser.add_argument(
        "mode", choices=['wms', 'wfs'],
        help="Available modes: wms, wfs"
    )
    parser.add_argument(
        "destination",
        help="Directory where the generated QGS and QML assets should be saved in"
    )
    parser.add_argument(
        "qgisVersion", choices=['2', '3'],
        help="Wether to use the QGIS 2 or QGIS 3 service template"
    )
    parser.add_argument(
        '--qgsTemplateDir',
        help="Path to template directory (default: 'qgs/')",
        default="qgs/", nargs='?'
    )
    parser.add_argument(
        '--qgsName',
        help="Target name of generated QGS file (default: 'somap')",
        default='somap', nargs='?'
    )
    parser.add_argument(
        "--log_level", choices=['info', 'debug'], default="info", nargs='?',
        help="Specifies the log level (default: info)"
    )
    args = parser.parse_args()

    # read Json2Qgs config file
    try:
        with open(args.qgsContent) as f:
            # parse config JSON with original order of keys
            config = json.load(f, object_pairs_hook=OrderedDict)
    except Exception as e:
        print("Error loading qgsContent JSON:\n%s" % e)
        exit(1)

    if args.log_level == "debug":
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    # create logger
    logger = Logger("Json2Qgs", log_level)

    # create Json2Qgs
    generator = Json2Qgs(
        config, logger, args.destination,
        args.qgisVersion, args.qgsTemplateDir, args.qgsName)
    if not generator.can_generate:
        print(
            "Error: Generator stopped! Please check if all"
            " files that are needed exist in: %s" % args.qgsTemplateDir)
    elif args.mode == 'wms':
        generator.generate_wms_project()
    elif args.mode == 'wfs':
        generator.generate_wfs_project()
