import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Form, Input, Typography, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiErr, api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

/** One-shot first-run page: create the single admin account and enter. */
export default function Setup() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    setBusy(true)
    try {
      await api.post('/api/auth/setup', values)
      await login(values.username, values.password)
      navigate('/')
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'SETUP_DONE') {
        message.info('管理员已存在，请直接登录')
        navigate('/login')
      } else if (err instanceof ApiErr) {
        message.error(err.message)
      } else {
        throw err
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
      <Card style={{ width: 380 }}>
        <Typography.Title level={4} style={{ textAlign: 'center' }}>
          初始化 Ontology Workbench
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          创建管理员账号（仅需一次）
        </Typography.Paragraph>
        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="username"
            rules={[{ min: 3, required: true, message: '用户名至少 3 个字符' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            rules={[{ min: 8, required: true, message: '密码至少 8 位' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            创建并进入
          </Button>
        </Form>
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          message="凭据仅存于本地数据库，不会离开这台服务器"
        />
      </Card>
    </div>
  )
}
