import { AutoChart, BackEndChartType, getChartType } from '@/components/chart/autoChart';
import { formatSql } from '@/utils';
import { Datum } from '@antv/ava';
import { Table, Tabs, TabsProps } from 'antd';
import { CodePreview } from './code-preview';
import VersionComparison, { type VersionComparisonRow } from './version-comparison';

function ChartView({
  data,
  type,
  sql,
  analysisReport,
  timings,
  semanticDecision,
  versionComparison,
  validationWarnings,
  sqlStructure,
  runtimeFeatures,
  resultRowCount,
  resultColumnCount,
}: {
  data: Datum[];
  type: BackEndChartType;
  sql: string;
  analysisReport?: string;
  timings?: Record<string, number | boolean | null>;
  semanticDecision?: Record<string, unknown>;
  versionComparison?: VersionComparisonRow[];
  validationWarnings?: string[];
  sqlStructure?: Record<string, unknown>;
  runtimeFeatures?: Record<string, unknown>;
  resultRowCount?: number;
  resultColumnCount?: number;
}) {
  const columns = data?.[0]
    ? Object.keys(data?.[0])?.map(item => {
        return {
          title: item,
          dataIndex: item,
          key: item,
        };
      })
    : [];
  const ChartItem = {
    key: 'chart',
    label: 'Chart',
    children: <AutoChart data={data} chartType={getChartType(type)} />,
  };
  const SqlItem = {
    key: 'sql',
    label: 'SQL',
    children: <CodePreview language='sql' code={formatSql(sql ?? '', 'mysql') as string} />,
  };
  const DataItem = {
    key: 'data',
    label: 'Data',
    children: <Table dataSource={data} columns={columns} scroll={{ x: 'auto' }} />,
  };
  const ReportItem = analysisReport
    ? {
        key: 'analysis_report',
        label: 'Analysis Report',
        children: (
          <pre className='max-h-[520px] overflow-auto whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-sm leading-6 dark:bg-gray-900'>
            {analysisReport}
          </pre>
        ),
      }
    : null;
  const DiagnosticsItem = timings
    ? {
        key: 'diagnostics',
        label: 'Diagnostics',
        children: (
          <pre className='max-h-[520px] overflow-auto rounded-md bg-gray-50 p-3 text-xs leading-5 dark:bg-gray-900'>
            {JSON.stringify(
              {
                timings,
                runtime_features: runtimeFeatures,
                result_row_count: resultRowCount,
                result_column_count: resultColumnCount,
              },
              null,
              2,
            )}
          </pre>
        ),
      }
    : null;
  const AlertsItem = validationWarnings?.length
    ? {
        key: 'alerts',
        label: 'Alerts',
        children: (
          <pre className='max-h-[520px] overflow-auto rounded-md bg-amber-50 p-3 text-xs leading-5 dark:bg-amber-950'>
            {validationWarnings.join('\n')}
          </pre>
        ),
      }
    : null;
  const StructureItem = sqlStructure
    ? {
        key: 'sql_structure',
        label: 'SQL Structure',
        children: (
          <pre className='max-h-[520px] overflow-auto rounded-md bg-gray-50 p-3 text-xs leading-5 dark:bg-gray-900'>
            {JSON.stringify(sqlStructure, null, 2)}
          </pre>
        ),
      }
    : null;
  const SemanticsItem = semanticDecision
    ? {
        key: 'semantics',
        label: 'Semantics',
        children: (
          <pre className='max-h-[520px] overflow-auto rounded-md bg-gray-50 p-3 text-xs leading-5 dark:bg-gray-900'>
            {JSON.stringify(semanticDecision, null, 2)}
          </pre>
        ),
      }
    : null;
  const ComparisonItem = versionComparison?.length
    ? {
        key: 'version_comparison',
        label: 'Version Comparison',
        children: <VersionComparison rows={versionComparison} />,
      }
    : null;
  const TabItems = (type === 'response_table' ? [DataItem, SqlItem] : [ChartItem, SqlItem, DataItem]) as NonNullable<
    TabsProps['items']
  >;
  if (ReportItem) {
    TabItems.push(ReportItem);
  }
  if (DiagnosticsItem) {
    TabItems.push(DiagnosticsItem);
  }
  if (AlertsItem) {
    TabItems.push(AlertsItem);
  }
  if (StructureItem) {
    TabItems.push(StructureItem);
  }
  if (SemanticsItem) {
    TabItems.push(SemanticsItem);
  }
  if (ComparisonItem) {
    TabItems.push(ComparisonItem);
  }

  return <Tabs defaultActiveKey={type === 'response_table' ? 'data' : 'chart'} items={TabItems} size='small' />;
}

export default ChartView;
