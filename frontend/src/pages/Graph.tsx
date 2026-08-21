import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Result, Space, Spin, Typography } from 'antd'
import { useMemo } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { NodesEdges } from '../api/types'
import GraphView, { type GraphViewNode } from '../components/GraphView'

/** Whole-ontology overview canvas; degrades to the top 3 levels past 500. */
export default function Graph() {
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  const focus = sp.get('focus')
  const navigate = useNavigate()
  const { data, isError, error, refetch } = useQuery({
    queryKey: ['overview', oid],
    queryFn: () => api.get<NodesEdges>(`/api/ontologies/${oid}/overview`),
    retry: false,
  })

  const nodes: GraphViewNode[] = useMemo(
    () => (data?.nodes ?? []).map((n) => (n.id === focus ? { ...n, highlighted: true } : n)),
    [data, focus],
  )

  if (isError) {
    const missing = error instanceof ApiErr && error.code === 'NOT_FOUND'
    return missing ? (
      <Result
        status="404"
        title="本体不存在"
        subTitle="它可能已被删除，或不属于当前用户。"
        extra={
          <Link to="/">
            <Button type="primary">返回首页</Button>
          </Link>
        }
      />
    ) : (
      <Result
        status="warning"
        title="加载失败"
        subTitle="无法连接服务器，请确认后端已启动。"
        extra={
          <Button type="primary" onClick={() => void refetch()}>
            重试
          </Button>
        }
      />
    )
  }
  if (!data) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  return (
    <div
      style={{
        height: '100vh',
        padding: '12px 20px',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          总览图
        </Typography.Title>
        <Link to={`/browse/${oid}`}>
          <Button size="small">返回工作区</Button>
        </Link>
      </Space>
      {data.truncated && (
        <Alert
          type="info"
          showIcon
          message={`本体超过 500 实体，仅显示顶层 3 层（共 ${data.totalCount}）`}
        />
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <GraphView
          nodes={nodes}
          edges={data.edges}
          focusId={focus ?? undefined}
          onSelect={(eid) => navigate(`/browse/${oid}?eid=${encodeURIComponent(eid)}`)}
        />
      </div>
    </div>
  )
}
