import discord
from discord.ext import commands
import pandas as pd
import os
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

        # Cargar catálogo de productos
        print("📥 Cargando productcatalogue.csv...")
        catalogue_df = pd.read_csv(catalogue_path, encoding='latin1', delimiter=';')
        print(f"✅ Catálogo: {len(catalogue_df)} registros")

        # Fusionar por ID de producto
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
        if self.df is None:
            self.load_data()
        mask = self.df['expansionName'].str.lower() == expansion_name.lower()
        return self.df[mask]

    def compare_expansions(self, old_exp: str, new_exp: str, top_n: int = 10):
        if self.df is None:
            self.load_data()

        old = self.get_prices_by_expansion(old_exp)
        new = self.get_prices_by_expansion(new_exp)

        if old.empty or new.empty:
            return None, "No se encontró una o ambas expansiones."

        merged = pd.merge(
            old[['productName', 'priceGuideSell']],
            new[['productName', 'priceGuideSell']],
            on='productName',
            suffixes=('_old', '_new')
        )

        merged['diff'] = merged['priceGuideSell_new'] - merged['priceGuideSell_old']
        merged['pct_change'] = (merged['diff'] / merged['priceGuideSell_old']) * 100

        top = merged.nlargest(top_n, 'pct_change')
        return top, None


class MkmCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.loader = MkmPriceLoader(data_dir="data")
        # Cargar datos en segundo plano al iniciar
        self.bot.loop.create_task(self.load_data_async())

    async def load_data_async(self):
        try:
            self.loader.load_data()
            print("✅ Datos MKM cargados correctamente")
        except Exception as e:
            print(f"❌ Error cargando datos MKM: {e}")

    @commands.command(name="mkm-subida")
    async def price_rise(self, ctx, old_exp: str, new_exp: str):
        """Compara precios entre dos ediciones. Ej: !mkm-subida "Ice Age" "Scourge" """
        if self.loader.df is None:
            await ctx.send("⏳ Los datos de precios aún no están cargados. Intenta en unos segundos.")
            return

        top, error = self.loader.compare_expansions(old_exp, new_exp)
        if error:
            await ctx.send(f"❌ {error}")
            return
        if top is None or top.empty:
            await ctx.send("⚠️ No hay datos para comparar esas ediciones.")
            return

        mensaje = "📈 **Top 10 cartas que más han subido:**\n"
        for idx, row in top.iterrows():
            mensaje += f"{idx+1}. **{row['productName']}**: {row['priceGuideSell_old']:.2f}€ → {row['priceGuideSell_new']:.2f}€ (+{row['pct_change']:.1f}%)\n"

        await ctx.send(mensaje)


async def setup(bot):
    await bot.add_cog(MkmCog(bot))