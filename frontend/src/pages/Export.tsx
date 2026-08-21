import { useMutation, useQuery } from '@tanstack/react-query'
import { ExportOutlined } from '@ant-design/icons'
import { Button, Card, Input, Result, Space, Spin, Switch, Typography, message } from 'antd'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { ExportSiteResult, OntologyMeta } from '../api/types'

/** Docs-site export page: output-dir option, force switch, copyable result path. */
export default function Export() {
  const { oid = '' } = useParams()
  const [outDir, setOutDir] = useState('')
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<ExportSiteResult | null>(null)

  const { data: meta, isError, error, refetch } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    retry: false,
  })

  const run = useMutation({
    mutationFn: () =>
      api.post<ExportSiteResult>(`/api/ontologies/${oid}/export/site`, {
        outDir: outDir.trim() || undefined,
        force,
      }),
    onSuccess: (data) => {
      setResult(data)
      message.success(`导出完成，共 ${data.pageCount} 页`)
    },
    onError: (err) => {
      message.error(err instanceof ApiErr ? err.message : '导出失败，请稍后重试')
    },
  })

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
  if (!meta) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 760, margin: '0 auto' }}>
      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
        <Typography.Title level={5} style={{ margin: 0 }}>
          导出文档站 — {meta.title}
        </Typography.Title>
        <Link to={`/browse/${oid}`}>
          <Button size="small">返回工作区</Button>
        </Link>
      </Space>

      <Card size="small" style={{ marginTop: 12 }}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div>
            <Typography.Text type="secondary">输出目录（可选）</Typography.Text>
            <Input
              style={{ marginTop: 4 }}
              placeholder="留空使用默认：{数据目录}/exports/{id}-{时间戳}"
              value={outDir}
              onChange={(e) => setOutDir(e.target.value)}
              disabled={run.isPending}
            />
          </div>
          <Space>
            <Switch checked={force} onChange={setForce} disabled={run.isPending} />
            <Typography.Text>覆盖非空目录（force）</Typography.Text>
          </Space>
          <div>
            <Button
              type="primary"
              icon={<ExportOutlined />}
              loading={run.isPending}
              onClick={() => run.mutate()}
            >
              开始导出
            </Button>
          </div>
        </Space>
      </Card>

      {result && (
        <Card size="small" title="导出结果" style={{ marginTop: 12 }}>
          <Space direction="vertical" size={4}>
            <Typography.Paragraph style={{ marginBottom: 0 }} copyable={{ text: result.outputDir }}>
              目录：{result.outputDir}
            </Typography.Paragraph>
            <Typography.Text type="secondary">
              共 {result.pageCount} 页（1 个索引页 + {result.pageCount - 1} 个实体页）
            </Typography.Text>
            <Typography.Text type="secondary">
              站点已写入服务器本地目录；在服务器上打开上述路径中的 index.html 即可浏览。
            </Typography.Text>
          </Space>
        </Card>
      )}
    </div>
  )
}
