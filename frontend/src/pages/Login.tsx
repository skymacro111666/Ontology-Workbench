import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Button, Card, Form, Input, Typography, message } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiErr } from '../api/client'
import { useAuth } from '../auth/AuthContext'

/** JWT login; error copy branches on the envelope code. */
export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  const onFinish = async (values: { username: string; password: string }) => {
    setBusy(true)
    try {
      await login(values.username, values.password)
      navigate('/')
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'AUTH_INVALID_CREDENTIALS') {
        message.error('用户名或密码错误')
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
      <Card style={{ width: 360 }}>
        <Typography.Title level={4} style={{ textAlign: 'center' }}>
          Ontology Workbench
        </Typography.Title>
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
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            登录
          </Button>
        </Form>
      </Card>
    </div>
  )
}
