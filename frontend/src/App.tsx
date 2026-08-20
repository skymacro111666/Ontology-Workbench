import { Layout, Typography } from 'antd'

/**
 * Scaffold shell. The route table and real pages mount in Tasks 15-18
 * (setup/login/home/browse); until then this placeholder proves the
 * toolchain (fonts, theme, build) end to end.
 */
export default function App() {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Content
        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}
      >
        <Typography.Title level={3} style={{ marginBottom: 4 }}>
          Ontology Workbench
        </Typography.Title>
        <Typography.Text type="secondary">frontend scaffold ready</Typography.Text>
      </Layout.Content>
    </Layout>
  )
}
