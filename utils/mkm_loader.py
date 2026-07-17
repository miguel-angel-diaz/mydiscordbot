import pandas as pd
import os
import asyncio
from datetime import datetime

class MkmPriceLoader:
    def __init__(self, data_dir="data"):
        self.data_dir = data_dir
        self.df = None
        self.last_load = None

    def load_data(self):
        """Carga los CSVs de precio y catálogo y los fusiona."""
        price_path = os.path.join(self.data_dir, "priceguide.csv")
        catalogue_path = os.path.join(self.data_dir, "productcatalogue.csv")

        if not os.path.exists(price_path) or not os.path.exists(catalogue_path):
            raise FileNotFoundError("No se encuentran los archivos CSV. Descárgalos de Cardmarket.")

        # Cargar guía de precios
        print("📥 Cargando priceguide.csv...")
        price_df = pd.read_csv(price_path, encoding='latin1', delimiter=';')
        print(f"✅ Price guide: {len(price_df)} registros")

        # Cargar catálogo de productos (contiene el nombre de la expansión)
        print("📥 Cargando productcatalogue.csv...")
        catalogue_df = pd.read_csv(catalogue_path, encoding='latin1', delimiter=';')
        print(f"✅ Catálogo: {len(catalogue_df)} registros")

        # Fusionar por ID de producto
        # El catálogo tiene 'idProduct' y 'expansionName'
        # La guía de precios tiene 'idProduct' y los precios
        self.df = pd.merge(
            price_df,
            catalogue_df[['idProduct', 'expansionName', 'productName']],
            on='idProduct',
            how='inner'
        )

        self.last_load = datetime.now()
        print(f"✅ Datos fusionados: {len(self.df)} cartas con precio y expansión")
        return self.df

    def get_prices_by_expansion(self, expansion_name: str):
        """Devuelve todas las cartas de una expansión con sus precios."""
        if self.df is None:
            self.load_data()
        # Búsqueda insensible a mayúsculas/minúsculas
        mask = self.df['expansionName'].str.lower() == expansion_name.lower()
        return self.df[mask]

    def get_card_price(self, card_name: str, expansion_name: str = None):
        """Obtiene el precio de una carta en una expansión concreta."""
        if self.df is None:
            self.load_data()

        mask = self.df['productName'].str.lower() == card_name.lower()
        if expansion_name:
            mask &= self.df['expansionName'].str.lower() == expansion_name.lower()

        result = self.df[mask]
        if result.empty:
            return None
        # Devolver el primer resultado (puede haber varias versiones)
        return result.iloc[0]

    def compare_expansions(self, old_exp: str, new_exp: str, top_n: int = 10):
        """Compara precios entre dos expansiones y devuelve el top de subidas."""
        if self.df is None:
            self.load_data()

        old = self.get_prices_by_expansion(old_exp)
        new = self.get_prices_by_expansion(new_exp)

        if old.empty or new.empty:
            return None, "No se encontró una o ambas expansiones."

        # Unir por nombre de carta (productName)
        merged = pd.merge(
            old[['productName', 'priceGuideSell']],
            new[['productName', 'priceGuideSell']],
            on='productName',
            suffixes=('_old', '_new')
        )

        # Calcular diferencias
        merged['diff'] = merged['priceGuideSell_new'] - merged['priceGuideSell_old']
        merged['pct_change'] = (merged['diff'] / merged['priceGuideSell_old']) * 100

        # Ordenar y seleccionar top
        top = merged.nlargest(top_n, 'pct_change')

        return top, None

async def test():
    loader = MkmPriceLoader(data_dir="data")
    loader.load_data()

    # Ejemplo: ver cartas de "Scourge"
    scourge = loader.get_prices_by_expansion("Scourge")
    print(f"Cartas en Scourge: {len(scourge)}")
    print(scourge[['productName', 'priceGuideSell']].head())

    # Comparar Scourge vs Onslaught
    top, error = loader.compare_expansions("Scourge", "Onslaught")
    if error:
        print("Error:", error)
    else:
        print("\n📈 Top 10 subidas de Scourge a Onslaught:")
        print(top[['productName', 'priceGuideSell_old', 'priceGuideSell_new', 'pct_change']])

if __name__ == "__main__":
    asyncio.run(test())