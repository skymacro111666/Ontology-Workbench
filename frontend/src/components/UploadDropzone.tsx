import { InboxOutlined } from '@ant-design/icons'
import { Upload, message } from 'antd'
import type { UploadProps } from 'antd'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { ApiErr, api } from '../api/client'
import type { OntologyMeta } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'

const MAX_BYTES = 150 * 1024 * 1024
const ACCEPT = '.ttl,.owl,.rdf,.jsonld,.json'

/** True when the file fits the 150MB upload limit. */
export function checkFileSize(file: { size: number; name: string }): boolean {
  if (file.size > MAX_BYTES) {
    message.error(`「${file.name}」超过 150MB 上限`)
    return false
  }
  return true
}

/** Drag-drop uploader; on success lands on the new ontology's browse page. */
export default function UploadDropzone() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const mutation = useMutation({
    mutationFn: (file: File) => api.upload<OntologyMeta>(file),
    onSuccess: (meta) => {
      void queryClient.invalidateQueries({ queryKey: ['ontologies'] })
      localStorage.setItem(LAST_OID_KEY, meta.id)
      navigate(`/browse/${meta.id}`)
    },
    onError: (err) => {
      if (err instanceof ApiErr && err.code === 'DUPLICATE_FILENAME') {
        message.error('同名本体已存在，请重命名或先删除')
      } else if (err instanceof ApiErr) {
        message.error(err.message)
      }
    },
  })

  const uploadProps: UploadProps = {
    accept: ACCEPT,
    multiple: false,
    showUploadList: false,
    beforeUpload: (file) => checkFileSize(file),
    customRequest: ({ file }) => {
      if (file instanceof File) mutation.mutate(file)
    },
  }

  return (
    <Upload.Dragger {...uploadProps}>
      <p className="ant-upload-drag-icon">
        <InboxOutlined />
      </p>
      <p className="ant-upload-text">点击或拖拽文件到此处上传本体</p>
      <p className="ant-upload-hint">支持 .ttl / .owl / .rdf / .jsonld，单个文件 ≤ 150MB</p>
    </Upload.Dragger>
  )
}
