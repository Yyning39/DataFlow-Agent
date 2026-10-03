import { BackEndChartType } from '@/components/chart';
import { Datum } from '@antv/ava';
import ChartView from './chart-view';
import { type VersionComparisonRow } from './version-comparison';

interface Props {
  data: {
    data: Datum[];
    describe: string;
    title: string;
    type: BackEndChartType;
    sql: string;
    analysis_report?: string;
    timings?: Record<string, number | boolean | null>;
    semantic_decision?: Record<string, unknown>;
    version_comparison?: VersionComparisonRow[];
    validation_warnings?: string[];
    sql_structure?: Record<string, unknown>;
    runtime_features?: Record<string, unknown>;
    result_row_count?: number;
    result_column_count?: number;
  };
}

function VisChart({ data }: Props) {
  if (!data) {
    return null;
  }
  return (
    <ChartView
      data={data?.data}
      type={data?.type}
      sql={data?.sql}
      analysisReport={data?.analysis_report}
      timings={data?.timings}
      semanticDecision={data?.semantic_decision}
      versionComparison={data?.version_comparison}
      validationWarnings={data?.validation_warnings}
      sqlStructure={data?.sql_structure}
      runtimeFeatures={data?.runtime_features}
      resultRowCount={data?.result_row_count}
      resultColumnCount={data?.result_column_count}
    />
  );
}

export default VisChart;
