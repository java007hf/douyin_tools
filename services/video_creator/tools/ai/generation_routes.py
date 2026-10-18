"""Provider-neutral generation routes used by AI Video asset tools."""

def image_generation_fields(config, spec, brief='', provider=None):
    return {'provider_id':str(config.get('default_image_provider_id') or 'local'),
            'model':str(config.get('default_image_model') or (provider or {}).get('model') or 'flux'),
            'prompt':str(spec.get('prompt') or brief),'count':'1','aspect':'16:9','resolution':'2K'}
