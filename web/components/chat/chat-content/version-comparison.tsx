import { Table } from 'antd';

export type VersionComparisonRow = {
  version: string;
  sql_conversion_rate?: number | null;
  execution_success_rate?: number | null;
  result_correctness?: number | null;
  average_latency?: number | null;
  p50_latency?: number | null;
  p95_latency?: number | null;
  model_timeout_rate?: number | null;
};

function percent(value?: number | null) {
  return value === null || value === undefined ? '-' : `${(value * 100).toFixed(1)}%`;
}

function seconds(value?: number | null) {
  return value === null || value === undefined ? '-' : `${value.toFixed(2)}s`;
}

export default function VersionComparison({ rows }: { rows: VersionComparisonRow[] }) {
  const columns = [
    { title: 'Version', dataIndex: 'version', key: 'version' },
    { title: 'SQL conversion', dataIndex: 'sql_conversion_rate', key: 'sql_conversion_rate', render: percent },
    { title: 'Execution success', dataIndex: 'execution_success_rate', key: 'execution_success_rate', render: percent },
    { title: 'Result correctness', dataIndex: 'result_correctness', key: 'result_correctness', render: percent },
    { title: 'Average latency', dataIndex: 'average_latency', key: 'average_latency', render: seconds },
    { title: 'P50', dataIndex: 'p50_latency', key: 'p50_latency', render: seconds },
    { title: 'P95', dataIndex: 'p95_latency', key: 'p95_latency', render: seconds },
    { title: 'Timeout rate', dataIndex: 'model_timeout_rate', key: 'model_timeout_rate', render: percent },
  ];
  return (
    <Table
      rowKey='version'
      size='small'
      pagination={false}
      dataSource={rows}
      columns={columns}
      scroll={{ x: 'auto' }}
    />
  );
}
