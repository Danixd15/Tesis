import warnings
import pandas as pd
import plotly.express as px
import streamlit as st

# =========================================================
# IMPORTACIÓN DE MÓDULOS LOCALES
# =========================================================
# Cambiamos leer_archivo_subido por convertir_a_mensual ya que procesaremos el Excel aquí
from datos import generar_demanda_sintetica, convertir_a_mensual 
from generar_pronosticos import METODOS_PRONOSTICO, generar_forecast, generar_forecast_mejor_por_producto
from simulacion_inventario import ParametrosInventario, simular_producto, calcular_kpis, optimizar_stock_seguridad, obtener_parametros_producto
from visualizacion import grafico_forecast, grafico_inventario, grafico_tradeoff, formatear_comparacion

warnings.filterwarnings("ignore")

# =========================================================
# CONFIGURACIÓN GENERAL
# =========================================================
st.set_page_config(
    page_title="Inventory Intelligence Framework",
    page_icon="📦",
    layout="wide",
)

st.title("📦 Framework de Optimización de Inventarios")
st.caption(
    "Pronóstico mensual + selección automática del mejor método por producto + simulación + optimización de inventarios"
)

# =========================================================
# SIDEBAR - CARGA DE DATOS ÚNICA
# =========================================================
st.sidebar.header("1. Carga de datos")
modo_datos = st.sidebar.radio("Modo de datos", ["Generar datos sintéticos", "Subir Excel (Pestañas: Demanda y Datos)"])

if modo_datos == "Generar datos sintéticos":
    n_productos = st.sidebar.slider("Número de productos", 1, 50, 5)
    meses = st.sidebar.slider("Meses de historial", 12, 84, 36)
    seed = st.sidebar.number_input("Semilla", min_value=1, max_value=9999, value=42)
    df_real = generar_demanda_sintetica(n_productos=n_productos, meses=meses, seed=seed)
    df_parametros = pd.DataFrame() # Creamos un df vacío para que use los parámetros por defecto
else:
    archivo = st.sidebar.file_uploader("Sube tu archivo Excel unificado", type=["xlsx", "xls"])
    if archivo is None:
        st.info(
            "Sube un archivo Excel que contenga dos pestañas:\n"
            "1. 'Demanda': Con el historial (date, product_id, demand_real)\n"
            "2. 'Datos': Con el maestro de artículos (GRUPO DE DEMANDA, lead_time, etc.)"
        )
        st.stop()

    try:
        # 1. Leer el libro de Excel completo
        xls = pd.ExcelFile(archivo)
        
        # 2. Extraer y procesar la pestaña "Demanda"
        if "Demanda" in xls.sheet_names:
            df_demanda_raw = pd.read_excel(xls, sheet_name="Demanda")
        else:
            df_demanda_raw = pd.read_excel(xls, sheet_name=0) # Si no se llama Demanda, toma la primera hoja
            
        # Normalizamos las columnas de la demanda para evitar errores tipográficos
        df_demanda_raw.columns = [str(c).strip().lower() for c in df_demanda_raw.columns]
        alias = {
            "fecha": "date", "mes": "date", "periodo": "date", "día": "date", "dia": "date",
            "producto": "product_id", "sku": "product_id", "id_producto": "product_id", "codigo": "product_id", "código": "product_id",
            "demanda": "demand_real", "venta": "demand_real", "ventas": "demand_real", "cantidad": "demand_real", "unidades": "demand_real",
        }
        df_demanda_raw = df_demanda_raw.rename(columns={c: alias.get(c, c) for c in df_demanda_raw.columns})
        
        # Pasamos los datos limpios a la función que los agrupa por mes
        df_real = convertir_a_mensual(df_demanda_raw)

        # 3. Extraer la pestaña "Datos" (Maestro de Artículos)
        if "Datos" in xls.sheet_names:
            df_parametros = pd.read_excel(xls, sheet_name="Datos")
        else:
            st.error("⚠️ El archivo Excel no tiene una pestaña llamada 'Datos'. Por favor, agrégala y vuelve a subir el archivo.")
            st.stop()

    except Exception as e:
        st.error(f"Error procesando el archivo: {str(e)}")
        st.stop()

# =========================================================
# PRONÓSTICO MENSUAL
# =========================================================
st.sidebar.header("2. Pronóstico mensual")
modo_pronostico = st.sidebar.selectbox(
    "Selección del método",
    ["Automático: mejor método por producto", "Manual: elegir un método"],
)

ultima_fecha_historica = pd.to_datetime(df_real["date"].max()).to_period("M").to_timestamp()
fecha_fin_pronostico = st.sidebar.date_input(
    "Pronosticar hasta",
    value=pd.Timestamp("2026-12-01"),
    min_value=ultima_fecha_historica.date(),
)
fecha_fin_pronostico = pd.to_datetime(fecha_fin_pronostico).to_period("M").to_timestamp()

df_forecast_auto, df_comparacion = generar_forecast_mejor_por_producto(
    df_real, fecha_fin_pronostico=fecha_fin_pronostico
)

if modo_pronostico == "Manual: elegir un método":
    metodo_manual = st.sidebar.selectbox("Método manual", METODOS_PRONOSTICO)
    df_forecast = generar_forecast(df_real, metodo_manual, fecha_fin_pronostico=fecha_fin_pronostico)
else:
    metodo_manual = None
    df_forecast = df_forecast_auto

productos = sorted(df_forecast["product_id"].unique())
producto_sel = st.sidebar.selectbox("Producto a visualizar", productos)

sub_comparacion_producto = df_comparacion[df_comparacion["Producto"] == producto_sel].copy()
mejor_metodo_producto = sub_comparacion_producto.loc[sub_comparacion_producto["Es mejor"], "Método"].iloc[0]
mejor_wmape_producto = sub_comparacion_producto.loc[sub_comparacion_producto["Es mejor"], "wMAPE"].iloc[0]

if modo_pronostico == "Automático: mejor método por producto":
    st.sidebar.success(f"Método elegido para {producto_sel}: {mejor_metodo_producto}")
else:
    st.sidebar.info(f"Mejor método para {producto_sel}: {mejor_metodo_producto}")

# =========================================================
# POLÍTICA DE INVENTARIO
# =========================================================
st.sidebar.header("3. Política de Inventario")

politica = st.sidebar.selectbox(
    "Política (Modo Simulación)",
    [
        "RS - revisión periódica",
        "sS - punto de reorden y nivel máximo",
        "sQ - punto de reorden y cantidad fija",
    ],
)

ss_max = st.sidebar.slider("Máximo SS para optimizar (meses)", 1, 24, 6)

# Extracción automática de parámetros desde la pestaña "Datos"
parametros_del_producto = obtener_parametros_producto(df_parametros, producto_sel)

# =========================================================
# CONTENIDO PRINCIPAL
# =========================================================
sub_forecast = df_forecast[df_forecast["product_id"] == producto_sel].copy()
metodo_usado = sub_forecast["method_used"].iloc[0]

# Ejecutar simulaciones
sub_sim = simular_producto(sub_forecast, politica, parametros_del_producto)
kpis = calcular_kpis(sub_sim, parametros_del_producto)
sub_opt = optimizar_stock_seguridad(sub_forecast, politica, parametros_del_producto, ss_max=ss_max)
mejor = sub_opt.loc[sub_opt["total_cost"].idxmin()]

# Tarjetas KPI
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Método usado", metodo_usado)
col2.metric("Fill rate", f"{kpis['fill_rate']:.2%}")
col3.metric("Inventario promedio", f"{kpis['avg_inventory']:.1f}")
col4.metric("Ventas perdidas", f"{kpis['lost_sales_units']:.0f}")
col5.metric("Costo total", f"S/ {kpis['total_cost']:,.2f}")

st.divider()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏆 Mejor método",
    "📊 Datos y pronóstico",
    "📦 Simulación",
    "🎯 Optimización",
    "📋 Tablas",
])

with tab1:
    st.subheader("🏆 Análisis Estratégico: Mejor Método por Producto")
    st.write(
        "El framework evalúa todos los modelos mediante Validación Cruzada y selecciona el ganador "
        "basado en el menor wMAPE, utilizando el RMSE y el Bias como criterios de desempate."
    )

    # Preparar el dataframe de los ganadores
    resumen_mejores = (
        df_comparacion[df_comparacion["Es mejor"]]
        .copy()
        .sort_values("Producto")
    )
    resumen_mejores = resumen_mejores[["Producto", "Método", "wMAPE", "Bias", "MAE"]].rename(
        columns={"Método": "Mejor método"}
    )

    # ==========================================
    # 1. RESUMEN DEL PORTAFOLIO (DONUT CHART)
    # ==========================================
    col_graf, col_tabla = st.columns([1.2, 1])

    # Contar cuántos productos ganaron con cada método
    conteo_metodos = resumen_mejores["Mejor método"].value_counts().reset_index()
    conteo_metodos.columns = ["Método", "Cantidad de Productos"]
    conteo_metodos["Porcentaje"] = (conteo_metodos["Cantidad de Productos"] / len(resumen_mejores)) * 100

    with col_graf:
        fig_donut = px.pie(
            conteo_metodos, 
            names="Método", 
            values="Cantidad de Productos", 
            hole=0.45,
            title="Distribución de Métodos Ganadores",
            color_discrete_sequence=px.colors.qualitative.Set2
        )
        fig_donut.update_traces(textposition='inside', textinfo='percent+label')
        fig_donut.update_layout(margin=dict(t=40, b=0, l=0, r=0))
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_tabla:
        st.write("<br>", unsafe_allow_html=True) # Espacio para centrar verticalmente
        st.markdown("**Resumen de Asignación de Modelos**")
        st.dataframe(
            conteo_metodos,
            hide_index=True,
            use_container_width=True,
            column_config={
                "Cantidad de Productos": st.column_config.ProgressColumn(
                    "Cantidad",
                    format="%d",
                    min_value=0,
                    max_value=int(conteo_metodos["Cantidad de Productos"].max())
                ),
                "Porcentaje": st.column_config.NumberColumn(
                    "% del Portafolio",
                    format="%.1f %%"
                )
            }
        )

    st.divider()

    # ==========================================
    # 2. DETALLE INTERACTIVO POR PRODUCTO
    # ==========================================
    st.subheader("🔎 Detalle por Producto")
    
    # Filtro interactivo
    metodos_disponibles = conteo_metodos["Método"].tolist()
    filtro_metodos = st.multiselect(
        "Filtra la tabla por Método Ganador:", 
        options=metodos_disponibles, 
        default=metodos_disponibles
    )

    # Aplicar el filtro y formatear los números a porcentajes (x100) para visualización
    df_mostrar = resumen_mejores[resumen_mejores["Mejor método"].isin(filtro_metodos)].copy()
    df_mostrar["wMAPE"] = df_mostrar["wMAPE"] * 100
    df_mostrar["Bias"] = df_mostrar["Bias"] * 100

    # Mostrar la tabla estilizada
    st.dataframe(
        df_mostrar,
        hide_index=True,
        use_container_width=True,
        column_config={
            "wMAPE": st.column_config.NumberColumn(
                "wMAPE (%)",
                help="Error Porcentual Absoluto Medio Ponderado",
                format="%.2f %%"
            ),
            "Bias": st.column_config.NumberColumn(
                "Bias (%)",
                help="Sesgo del pronóstico (Positivo = Sobrepronóstico, Negativo = Subpronóstico)",
                format="%.2f %%"
            ),
            "MAE": st.column_config.NumberColumn(
                "MAE (Unidades)",
                format="%.2f"
            )
        }
    )

    st.write("<br>", unsafe_allow_html=True)
    csv_mejores = resumen_mejores.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Descargar detalle completo en CSV",
        data=csv_mejores,
        file_name="mejor_metodo_por_producto.csv",
        mime="text/csv",
    )
    
with tab2:
    st.subheader("📊 Análisis de Demanda y Proyección")
    st.write("Visualización del comportamiento histórico frente al modelo de pronóstico seleccionado.")

    # Ajuste de Layout: Gráfico a la izquierda, métricas a la derecha
    col_g1, col_g2 = st.columns([3, 1])
    
    with col_g1:
        # Gráfico mejorado usando Plotly con áreas sombreadas
        fig = grafico_forecast(sub_forecast)
        fig.update_layout(
            template="plotly_white",
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_g2:
        st.markdown("### 🎯 Resumen del Modelo")
        st.metric("Método Seleccionado", metodo_usado)
        st.metric("wMAPE (Error)", f"{mejor_wmape_producto:.2%}")
        
        st.markdown("---")
        st.markdown("**Insights clave:**")
        if mejor_wmape_producto < 0.20:
            st.success("Modelo de alta precisión. Apto para compras automáticas.")
        elif mejor_wmape_producto < 0.50:
            st.warning("Modelo con precisión moderada. Se recomienda revisión manual.")
        else:
            st.error("Precisión baja. Posible demanda errática o quiebre de stock.")

    st.markdown("### 📋 Comparativa de Métodos (Validación Cruzada)")
    
    # Tabla interactiva con formato condicional
    df_comp = formatear_comparacion(sub_comparacion_producto)
    
    # Aplicar estilo: resaltar la fila que dice "✅ Mejor"
    def highlight_best(row):
        return ['background-color: #d4edda' if '✅' in str(val) else '' for val in row]
    
    st.dataframe(
        df_comp.style.apply(highlight_best, axis=1),
        use_container_width=True,
        hide_index=True
    )
    
with tab3:
    st.subheader("Simulación mensual de inventario")
    st.plotly_chart(grafico_inventario(sub_sim), use_container_width=True)

    st.write("KPIs de la simulación")
    kpi_df = pd.DataFrame([kpis]).T.reset_index()
    kpi_df.columns = ["Indicador", "Valor"]
    st.dataframe(kpi_df, use_container_width=True, hide_index=True)

with tab4:
    st.subheader("Optimización de stock de seguridad mensual")
    st.info(
        f"Para el producto {producto_sel}, usando el método de pronóstico {metodo_usado}, "
        f"el stock de seguridad óptimo encontrado es {int(mejor['ss_months'])} meses, "
        f"con costo total aproximado de S/ {mejor['total_cost']:,.2f}."
    )
    st.plotly_chart(grafico_tradeoff(sub_opt), use_container_width=True)

    fig_servicio = px.line(
        sub_opt,
        x="ss_months",
        y="fill_rate",
        markers=True,
        title="Nivel de servicio según meses de stock de seguridad",
        labels={"ss_months": "Meses de stock de seguridad", "fill_rate": "Fill rate"},
    )
    fig_servicio.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig_servicio, use_container_width=True)

with tab5:
    st.subheader("Tablas de resultados")
    st.write("Comparación completa de métodos")
    st.dataframe(formatear_comparacion(df_comparacion), use_container_width=True, hide_index=True)

    st.write("Datos mensuales históricos y pronóstico futuro elegido")
    st.dataframe(sub_forecast, use_container_width=True, hide_index=True)

    st.write("Simulación mensual")
    st.dataframe(sub_sim, use_container_width=True, hide_index=True)

    st.write("Resultados de optimización")
    st.dataframe(sub_opt, use_container_width=True, hide_index=True)

    csv = sub_sim.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar simulación mensual en CSV",
        data=csv,
        file_name=f"simulacion_mensual_{producto_sel}.csv",
        mime="text/csv",
    )

    csv_comparacion = df_comparacion.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Descargar comparación de métodos en CSV",
        data=csv_comparacion,
        file_name="comparacion_metodos_pronostico.csv",
        mime="text/csv",
    )
