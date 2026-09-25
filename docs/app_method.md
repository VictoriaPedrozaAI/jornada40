### Flujo
1. **Datos.** Una plantilla CSV con la programación real de la semana (una fila por turno, con salario diario) para 1 a 50 tiendas. Opcional: el requerimiento de personas por hora. Sin él, se conserva la cobertura actual de cada tienda.
2. **Estado actual.** Cada turno se clasifica como diurna (D), mixta (M) o nocturna (N) según sus horas entre 20:00 y 06:00 (arts. 60–61). Se cuentan las horas pagadas **dobles** (desde la hora 41 con el tope de 40 h, o por encima del máximo diario de su jornada) y **triples** (arts. 66–68), el trabajo en día de descanso o feriado (arts. 73 y 75, pago triple) y la prima dominical (art. 71).
3. **Nueva programación.** Se optimiza **cada tienda por separado** con CP-SAT en dos escenarios —**semana de 5 días** y **semana de 6 días**— y se comparan con el mismo motor de costos: ahorro = costo actual − costo propuesto. Tú eliges cuál ver y descargar.

### Chequeo de capacidad (antes de optimizar)
Con un turno por persona al día, dos momentos de demanda separados por al menos un turno no los puede cubrir la misma persona. Sumando esas demandas se obtiene un mínimo de persona-días por semana que se compara con lo que da el personal (personas × 5 o 6 días). 🔴 = habrá faltante en pico con ese tipo de semana; 🟡/🟢 = no se detecta un problema seguro (el optimizador da el resultado exacto).

### El optimizador: CP-SAT (Google OR-Tools 9.15)
CP-SAT es un solver de programación con restricciones que **demuestra** si una solución es óptima. Por tienda:
- **Tipos de semana legales** (la LFT solo exige **1 día de descanso por cada 6 trabajados**, art. 69; repartir las horas en 5 o 6 días es decisión de empresa y trabajador):
  - 5 días con turnos de 8 h (diurna) o 7.5 h (mixta) → 2 descansos;
  - 6 días con turnos de 6.5 h → 39 h y 1 descanso (en la transición: 6 × 7 h = 42 h, 6 × 7.5 h = 44–46 h);
  - opcional (solo en el escenario de 5 días): 6.º día completo pagado como hora extra.
- **Turnos candidatos**: de esas duraciones, con inicio cada 30 min dentro del horario de la tienda. Ninguno rebasa el máximo diario de su jornada.
- **Decisiones**: cuántas personas trabajan cada turno cada día y cuántos empleados siguen cada patrón semanal.
- **Restricciones**: cobertura cada 30 min; faltante en horas pico con penalización prohibitiva; nadie trabaja 7 días; nadie rebasa el tope semanal; todos los empleados de piso completan su semana.
- **Objetivo** (en centavos): horas extra + prima dominical + feriados + penalizaciones por faltante y por horas sobrantes.
- Después se asignan personas concretas: los salarios más bajos a los patrones más caros (domingo o 6.º día) y a cada persona un horario estable en la semana.

La pantalla de resultados muestra la **función objetivo desglosada** (qué pesó en la decisión) y una **cascada** de dónde sale el ahorro en pesos.

Cada tienda se resuelve de forma **óptima** en menos de un segundo; 50 tiendas en ~13 s.

### Supuestos a validar con el cliente
- Tarifa horaria = salario diario ÷ 8. Horas por encima del máximo diario del tipo de jornada = horas extra (criterio conservador).
- La prima dominical se suma al triple por descanso o feriado en domingo.
- El ahorro en efectivo no incluye cargas sociales (IMSS, INFONAVIT, ISN).
- Demo sintética: 50 tiendas × 80 empleados (72 de piso + 8 administrativos); tráfico con la forma del día del archivo de visitas del cliente; volumen, fines de semana y quincenas son supuestos.

### Limitaciones del MVP
- Un solo grupo de personal en piso (sin distinguir cajeros, piso o almacén).
- Menores de edad fuera del optimizador.
- Solo turnos de tiempo completo: dos picos separados ~8 h (10:00 y 18:00) no se cubren con la misma persona; las semanas de 6 días reducen ese faltante, pero queda algo de faltante fuera de pico y horas sobrantes a media tarde.
