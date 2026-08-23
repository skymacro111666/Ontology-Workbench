import { AlignJustifyIcon, ArrowLeftRightIcon, BoxesIcon, HexagonIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'

export interface StatTilesProps {
  ontologies: number
  classes: number
  properties: number
  axioms: number
}

/** Home header row: four KPI tiles — icon + uppercase micro-label + big number. */
export default function StatTiles({ ontologies, classes, properties, axioms }: StatTilesProps) {
  const tiles = [
    { label: '本体', value: ontologies, icon: BoxesIcon },
    { label: '类', value: classes, icon: HexagonIcon },
    { label: '属性', value: properties, icon: ArrowLeftRightIcon },
    { label: '公理', value: axioms, icon: AlignJustifyIcon },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map(({ label, value, icon: Icon }) => (
        <Card key={label} className="border-line rounded-card py-4">
          <CardContent className="flex items-center gap-3 px-4">
            <div
              aria-hidden
              className="bg-primary-soft text-primary flex size-10 shrink-0 items-center justify-center rounded-ctl"
            >
              <Icon className="size-5" />
            </div>
            <div className="flex flex-col gap-1">
              <span className="microlabel">{label}</span>
              {/* tabular-nums keeps digit columns aligned across tiles. */}
              <span className="tabular-nums text-2xl leading-none font-semibold">{value}</span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
