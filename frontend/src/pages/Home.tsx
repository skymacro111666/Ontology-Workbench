import { DeleteOutlined, FileTextOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Col, Empty, Modal, Result, Row, Space, Statistic, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta, OntologySummary } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'
import UploadDropzone from '../components/UploadDropzone'

const SAMPLES: { name: string; description: string }[] = [
  { name: 'pizza', description: '经典 Pizza 本体（类/属性/公理齐全）' },
  { name: 'wine', description: 'W3C Wine 本体（关系丰富）' },
  { name: 'foaf', description: 'FOAF 朋友的朋友（轻量词表）' },
]

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** Home: stats header, upload dropzone, ontology cards, builtin samples. */
export default function Home() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data, isError, refetch } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.get<{ items: OntologySummary[]; total: number }>('/api/ontologies'),
  })

  const openOntology = (id: string) => {
    localStorage.setItem(LAST_OID_KEY, id)
    navigate(`/browse/${id}`)
  }

  const del = useMutation({
    mutationFn: (id: string) => api.del(`/api/ontologies/${id}`),
    onSuccess: () => {
      message.success('已删除')
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
    },
    onError: (err) => {
      message.error(err instanceof ApiErr ? err.message : '操作失败，请稍后重试')
    },
  })

  const sample = useMutation({
    mutationFn: (name: string) => api.post<OntologyMeta>(`/api/samples/${name}`),
    onSuccess: (meta) => {
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      openOntology(meta.id)
    },
    onError: (err) => {
      message.error(err instanceof ApiErr ? err.message : '载入示例失败，请稍后重试')
    },
  })

  const items: OntologySummary[] = data?.items ?? []
  const totalClasses = items.reduce((sum, o) => sum + o.classCount, 0)
  const totalProperties = items.reduce((sum, o) => sum + o.propertyCount, 0)

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      <Typography.Title level={3}>我的本体</Typography.Title>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <Statistic title="本体" value={items.length} />
        </Col>
        <Col>
          <Statistic title="类" value={totalClasses} />
        </Col>
        <Col>
          <Statistic title="属性" value={totalProperties} />
        </Col>
      </Row>

      <UploadDropzone />

      <Typography.Title level={5} style={{ marginTop: 24 }}>
        内置示例
      </Typography.Title>
      <Row gutter={12}>
        {SAMPLES.map((s) => (
          <Col key={s.name}>
            <Card
              size="small"
              hoverable
              style={{ width: 220 }}
              onClick={() => sample.mutate(s.name)}
              loading={sample.isPending && sample.variables === s.name}
            >
              <Card.Meta title={s.name} description={s.description} />
            </Card>
          </Col>
        ))}
      </Row>

      <Typography.Title level={5} style={{ marginTop: 24 }}>
        本体列表
      </Typography.Title>
      {isError ? (
        <Result
          status="warning"
          title="列表加载失败"
          subTitle="无法连接服务器，请确认后端已启动。"
          extra={
            <Button type="primary" onClick={() => void refetch()}>
              重试
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <Empty description="还没有本体，先上传或载入示例" />
      ) : (
        <Row gutter={[12, 12]}>
          {items.map((o) => (
            <Col key={o.id} xs={24} md={12} lg={8}>
              <Card
                size="small"
                title={
                  <Space>
                    <FileTextOutlined />
                    <span>{o.title}</span>
                  </Space>
                }
                extra={
                  <Space>
                    <Button size="small" onClick={() => openOntology(o.id)}>
                      打开
                    </Button>
                    <Button
                      size="small"
                      danger
                      aria-label={`删除 ${o.title}`}
                      icon={<DeleteOutlined />}
                      onClick={() =>
                        Modal.confirm({
                          title: `删除「${o.title}」？`,
                          content: '文件与索引将一并移除，不可恢复。',
                          okText: '删除',
                          okButtonProps: { danger: true },
                          cancelText: '取消',
                          onOk: () => del.mutate(o.id),
                        })
                      }
                    />
                  </Space>
                }
              >
                <Space direction="vertical" size={2} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag>{o.format}</Tag>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {o.filename} · {formatSize(o.fileSizeBytes)}
                    </Typography.Text>
                  </Space>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {o.classCount} 类 · {o.propertyCount} 属性 · {o.axiomCount} 公理
                  </Typography.Text>
                </Space>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
