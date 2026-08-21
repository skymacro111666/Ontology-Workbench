import { useQuery } from '@tanstack/react-query'
import { Button, Layout, Result, Space, Spin, Typography } from 'antd'
import { Link, useParams } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta } from '../api/types'
import Breadcrumb from '../components/Breadcrumb'
import EntityDetail from '../components/EntityDetail'
import SearchBox from '../components/SearchBox'
import Sidebar from '../components/Sidebar'
import StatusBar from '../components/StatusBar'

const { Sider, Content, Footer } = Layout

/** Main workbench: tri-tab sidebar + content area + full-width status bar. */
export default function Browse() {
  const { oid = '' } = useParams()
  const { data: meta, isError, error, refetch } = useQuery({
    queryKey: ['ontology', oid],
    queryFn: () => api.get<OntologyMeta>(`/api/ontologies/${oid}/meta`),
    retry: false,
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
    <Layout style={{ height: '100vh' }}>
      {/* Inner layout carries the sider; the outer stays column-shaped so
          the Footer spans the full width below both sider and content. */}
      <Layout>
        <Sider width={304} theme="light" style={{ overflow: 'auto' }}>
          <Sidebar oid={oid} meta={meta} />
        </Sider>
        <Content style={{ padding: '12px 20px', overflow: 'auto' }}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {meta.title}
              </Typography.Title>
              <Space>
                <SearchBox oid={oid} />
                <Link to={`/graph/${oid}`}>
                  <Button size="small">总览图</Button>
                </Link>
                <Link to={`/export/${oid}`}>
                  <Button size="small">导出</Button>
                </Link>
              </Space>
            </Space>
            <Breadcrumb oid={oid} />
            <EntityDetail oid={oid} />
          </Space>
        </Content>
      </Layout>
      <Footer style={{ padding: '6px 20px' }}>
        <StatusBar meta={meta} />
      </Footer>
    </Layout>
  )
}
