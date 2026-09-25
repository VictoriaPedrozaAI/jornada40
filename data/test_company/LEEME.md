# Súper Palma — empresa simulada para probar Jornada40

Datos 100 % ficticios, generados con `python scripts/make_test_company.py` (semilla fija). Independientes de la demo.

- 24 supermercados (`SP-01` … `SP-24`); 4 en Tijuana (`zona = zlfn`, salario mínimo frontera).
- 1,938 empleados (≈ 66–93 por tienda): 4 administrativos + 2 vigilantes nocturnos (`en_piso = 0`) y personal de piso.
- Tienda abierta 08:00–21:00; semana regular **lunes 23 – domingo 29 nov 2026** (sin feriado).
- Empresa **en transición a 40 h**: el piso ya trabaja **6 días × 7 h = 42 h** (1 descanso, sobre todo mar–jue); turnos mañana 07:00–14:00, tarde 14:00–21:00, cierre 15:00–22:00. Aún hay ~8 % de turnos alargados 1 h y algunas personas llamadas en su descanso de fin de semana (15 casos, con 7 días seguidos). Vigilancia 22:00–05:00 (6 × 7 h, nocturna).
- Salarios diarios: piso 330–560 (frontera ≥ 446), administrativos 520–1,650.

## Archivos (formato exacto de la plantilla)
- `programacion_actual.csv` — obligatorio, una fila por turno (11,547 filas).
- `requerimiento.csv` — opcional, personas requeridas por tienda y hora 07–21 (2,520 filas).

## Recorrido de prueba
1. **Inicio → Ir a Datos** → descargar plantillas (comparar columnas con estos archivos).
2. Subir `programacion_actual.csv` (+ `requerimiento.csv`) → **Analizar mis archivos**.
3. **Diagnóstico** con "Tope de 40 h" (y, para comparar, "Transición — 42 h").
4. **Generar nueva programación** → comparar semana de 5 vs 6 días → descargar.
5. Variante: subir solo `programacion_actual.csv` (sin requerimiento).

## Resultados de referencia (verificados con el código)
| Escenario | Horas dobles actuales | Extras / costo | Faltante en pico actual | Ahorro 5 días | Ahorro 6 días |
|---|---|---|---|---|---|
| **Tope de 40 h** | 4,537 h ($453,849) | 10.0 % | 5,438 persona-h | **7.7 %** ($498,086/sem), pico cubierto, 5/24 tiendas ≥ 8 % | 7.2 %, faltante en pico (998 h) |
| Transición 42 h | 853 h ($85,055) | 4.5 % | 5,438 persona-h | 2.3 %, pico cubierto | 1.7 % |

Lectura: Súper Palma ya hizo casi toda la reducción (48 → 42 h). Con el tope de 40 h, cada persona de piso genera 2 h dobles por semana, más los turnos alargados y los descansos trabajados. La nueva programación elimina esas horas (salvo 96 h de los vigilantes, que no son de piso y no se optimizan) **y además cubre los picos que hoy quedan descubiertos** (5,438 → 0 persona-h). El ahorro queda cerca pero por debajo del 8 %: un caso realista para discutir.

Hallazgos esperados en el diagnóstico: 15 violaciones del art. 69 (7 días seguidos) y 15 descansos trabajados; después: 0 violaciones.
