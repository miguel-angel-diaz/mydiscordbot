# utils/cardmarket_downloader.py
import os
import aiohttp
import asyncio
import hashlib
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def descargar_si_cambio():
    """Descarga los CSVs si han cambiado (usa cookies de entorno)."""
    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    
    phpsessid = os.getenv('CARDMARKET_PHPSESSID')
    if not phpsessid:
        logger.warning("No hay PHPSESSID configurado. No se pueden descargar CSVs.")
        return {'priceguide': {'changed': False}, 'productcatalogue': {'changed': False}}
    
    cookies = {'PHPSESSID': phpsessid}
    if os.getenv('CARDMARKET_LANG'):
        cookies['mkm_lang'] = os.getenv('CARDMARKET_LANG')
    
    # URLs de descarga (pueden cambiar, revisar en la web)
    urls = {
        'priceguide': 'https://www.cardmarket.com/Data/Download/priceguide.csv',
        'productcatalogue': 'https://www.cardmarket.com/Data/Download/productcatalogue.csv'
    }
    
    result = {}
    for name, url in urls.items():
        filepath = data_dir / f"{name}.csv"
        # Descargar
        response = requests.get(url, cookies=cookies, stream=True)
        if response.status_code == 200:
            content = response.content
            new_hash = hashlib.md5(content).hexdigest()
            old_hash = None
            if filepath.exists():
                with open(filepath, 'rb') as f:
                    old_hash = hashlib.md5(f.read()).hexdigest()
            if old_hash != new_hash:
                with open(filepath, 'wb') as f:
                    f.write(content)
                result[name] = {'changed': True}
                logger.info(f"✅ {name}.csv actualizado")
            else:
                result[name] = {'changed': False}
        else:
            logger.error(f"❌ Error descargando {name}.csv: {response.status_code}")
            result[name] = {'changed': False}
    
    return result