"""Offline validator for exactly the JSON Schema keywords used by this contract.

Not a general Draft 2020-12 implementation. Unknown keywords fail closed.
Install jsonschema to use its complete validator instead.
"""
import re


class Error:
    def __init__(self, message):
        self.message = message
        self.context = []


class Draft202012Validator:
    SUPPORTED = {'$schema', '$defs', '$ref', 'title', 'description', 'default',
                 'type', 'properties', 'required', 'additionalProperties',
                 'oneOf', 'anyOf', 'allOf', 'if', 'then', 'enum', 'const',
                 'items', 'minItems', 'minLength', 'pattern', 'minimum', 'maximum'}

    def __init__(self, schema):
        self.schema = schema

    @classmethod
    def check_schema(cls, schema):
        def check(node):
            if isinstance(node, bool):
                return
            if not isinstance(node, dict):
                raise ValueError('Schema node must be object or boolean')
            unsupported = set(node) - cls.SUPPORTED
            if unsupported:
                raise ValueError('Offline backend does not support: '+str(sorted(unsupported)))
            for name in ['properties', '$defs']:
                for child in node.get(name, {}).values():
                    check(child)
            for name in ['oneOf', 'anyOf', 'allOf']:
                for child in node.get(name, []):
                    check(child)
            for name in ['items', 'if', 'then', 'additionalProperties']:
                if name in node:
                    check(node[name])
            if '$ref' in node:
                if not node['$ref'].startswith('#/$defs/') or node['$ref'].split('/')[-1] not in schema.get('$defs', {}):
                    raise ValueError('Only existing local $defs references are supported')
            if 'pattern' in node:
                re.compile(node['pattern'])
        check(schema)

    def iter_errors(self, value):
        self.check_schema(self.schema)

        def errors(node, item, path='$'):
            if isinstance(node, bool):
                return [] if node else [path+': forbidden']
            found = []
            if '$ref' in node:
                found += errors(self.schema['$defs'][node['$ref'].split('/')[-1]], item, path)
            if 'oneOf' in node:
                matches = sum(not errors(child, item, path) for child in node['oneOf'])
                if matches != 1:
                    found.append(f'{path}: oneOf matched {matches} branches')
            if 'anyOf' in node and not any(not errors(child, item, path) for child in node['anyOf']):
                found.append(path+': no anyOf branch matched')
            for child in node.get('allOf', []):
                found += errors(child, item, path)
            if 'if' in node and not errors(node['if'], item, path) and 'then' in node:
                found += errors(node['then'], item, path)
            def equal(a, b):
                # JSON booleans must not compare equal to numbers.
                return type(a) == type(b) and a == b
            if 'const' in node and not equal(item, node['const']):
                found.append(path+': wrong constant')
            if 'enum' in node and not any(equal(item, x) for x in node['enum']):
                found.append(path+': outside enum')
            types = {'object': isinstance(item, dict), 'array': isinstance(item, list),
                     'string': isinstance(item, str), 'integer': type(item) is int or (type(item) is float and item.is_integer()),
                     'boolean': type(item) is bool, 'null': item is None}
            if 'type' in node and not types.get(node['type'], False):
                return found+[path+': expected '+node['type']]
            if isinstance(item, dict):
                for name in node.get('required', []):
                    if name not in item:
                        found.append(path+': missing '+name)
                properties = node.get('properties', {})
                for name, child in item.items():
                    if name in properties:
                        found += errors(properties[name], child, path+'.'+name)
                    elif 'additionalProperties' in node:
                        found += errors(node['additionalProperties'], child, path+'.'+name)
            if isinstance(item, list):
                if len(item) < node.get('minItems', 0):
                    found.append(path+': too few items')
                if 'items' in node:
                    for i, child in enumerate(item):
                        found += errors(node['items'], child, f'{path}[{i}]')
            if isinstance(item, str):
                if len(item) < node.get('minLength', 0):
                    found.append(path+': string too short')
                if 'pattern' in node and re.search(node['pattern'], item) is None:
                    found.append(path+': pattern mismatch')
            if type(item) in (int, float):
                if 'minimum' in node and item < node['minimum']:
                    found.append(path+': below minimum')
                if 'maximum' in node and item > node['maximum']:
                    found.append(path+': above maximum')
            return found

        for message in errors(self.schema, value):
            yield Error(message)
