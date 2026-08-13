import { STATUS_COLORS, type LotStatus } from "./primitives";

type SchematicLot = {
  x: number;
  y: number;
  status: LotStatus;
};

const LOT_WIDTH = 38;
const LOT_HEIGHT = 52;
const COLUMN_PITCH = 42;
const ROW_PITCH = 56;

const BLOCKS = [
  { x: 26, y: 24, columns: 7 },
  { x: 350, y: 24, columns: 6 },
  { x: 26, y: 166, columns: 7 },
  { x: 350, y: 166, columns: 6 },
];

// Sequencia fixa (nao aleatoria) para o desenho nao mudar entre renders.
const STATUS_CYCLE: LotStatus[] = [
  "disponivel",
  "disponivel",
  "vendido",
  "disponivel",
  "reservado",
  "disponivel",
  "disponivel",
  "vendido",
  "disponivel",
  "disponivel",
  "reservado",
  "vendido",
  "disponivel",
];

const LOTS: SchematicLot[] = BLOCKS.flatMap((block, blockIndex) =>
  Array.from({ length: block.columns * 2 }, (_, index) => {
    const row = index < block.columns ? 0 : 1;
    const column = index % block.columns;
    return {
      x: block.x + column * COLUMN_PITCH,
      y: block.y + row * ROW_PITCH,
      status: STATUS_CYCLE[(blockIndex * 5 + index) % STATUS_CYCLE.length],
    };
  }),
);

const STREETS = [
  { x: 0, y: 138, width: 620, height: 24 },
  { x: 320, y: 0, width: 26, height: 298 },
];

/**
 * Representacao esquematica honesta: a mesma geometria desenhada duas vezes.
 * "blueprint" e o traco da planta em PDF; "map" e o mesmo traco com status.
 * Nao e captura de tela do produto.
 */
export function PlantSchematic({ mode }: { mode: "blueprint" | "map" }) {
  const isMap = mode === "map";

  return (
    <svg
      viewBox="0 0 620 298"
      className="h-full w-full"
      role="img"
      aria-label={
        isMap
          ? "Esquema do mesmo loteamento com cada lote pintado por status: verde disponivel, laranja reservado, cinza vendido"
          : "Esquema de uma planta em PDF: quadras e lotes apenas em traco cinza, sem informacao de status"
      }
    >
      {STREETS.map((street) => (
        <rect
          key={`${street.x}-${street.y}`}
          x={street.x}
          y={street.y}
          width={street.width}
          height={street.height}
          fill={isMap ? "#0F1D24" : "transparent"}
          stroke={isMap ? "rgba(255,255,255,0.10)" : "#4C5B62"}
          strokeWidth="1"
          strokeDasharray={isMap ? undefined : "5 4"}
        />
      ))}

      {LOTS.map((lot) => (
        <rect
          key={`${lot.x}-${lot.y}`}
          x={lot.x}
          y={lot.y}
          width={LOT_WIDTH}
          height={LOT_HEIGHT}
          rx="2"
          fill={isMap ? STATUS_COLORS[lot.status] : "none"}
          fillOpacity={isMap ? 0.82 : 0}
          stroke={isMap ? "rgba(6,12,16,0.6)" : "#6E6D67"}
          strokeWidth={isMap ? 1.5 : 1}
        />
      ))}

      {/* O gabarito impresso na planta: e dele que sai a conferencia do resultado. */}
      <text x="26" y="16" fontSize="10" letterSpacing="0.08em" fill={isMap ? "#94A6AE" : "#6E6D67"}>
        Q195 - 14 LOTES
      </text>
      <text x="350" y="16" fontSize="10" letterSpacing="0.08em" fill={isMap ? "#94A6AE" : "#6E6D67"}>
        Q196 - 12 LOTES
      </text>
      <text x="26" y="290" fontSize="10" letterSpacing="0.08em" fill={isMap ? "#94A6AE" : "#6E6D67"}>
        Q193 - 14 LOTES
      </text>
      <text x="350" y="290" fontSize="10" letterSpacing="0.08em" fill={isMap ? "#94A6AE" : "#6E6D67"}>
        Q194 - 12 LOTES
      </text>
    </svg>
  );
}
