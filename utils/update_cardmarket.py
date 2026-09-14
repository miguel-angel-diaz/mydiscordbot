#!/usr/bin/env python3
"""
Script para actualizar los CSVs de Cardmarket.
Ejecutar: python scripts/update_cardmarket.py
"""

import sys
from pathlib import Path

# Añadir el directorio raíz al path para poder importar utils
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.cardmarket_downloader import descargar_si_cambio
import logging

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    print("🔄 Verificando actualizaciones de Cardmarket...")
    result = descargar_si_cambio()
    
    if result['priceguide']['changed'] or result['productcatalogue']['changed']:
        print("✅ Archivos actualizados correctamente")
    else:
        print("ℹ️ No hay cambios en los CSVs")
    
    # Mostrar estado
    print(f"📊 PriceGuide: {'✅ Descargado' if result['priceguide']['downloaded'] else '📁 Actual'}")
    print(f"📊 ProductCatalogue: {'✅ Descargado' if result['productcatalogue']['downloaded'] else '📁 Actual'}")