import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useUiStore } from './uiStore'

beforeEach(() => {
  useUiStore.setState({
    sourceDirty: false,
    pendingView: null,
    sourceSaveFn: null,
    browseView: 'graph',
    importOpen: false,
    entityDialog: null,
    leftCollapsed: false,
    rightCollapsed: false,
  })
})

describe('uiStore source-editing fields', () => {
  it('tracks dirtiness and the pending view switch', () => {
    useUiStore.getState().setSourceDirty(true)
    expect(useUiStore.getState().sourceDirty).toBe(true)
    useUiStore.getState().setPendingView('graph')
    expect(useUiStore.getState().pendingView).toBe('graph')
  })

  it('registers and clears the save callback', async () => {
    const fn = vi.fn(async () => true)
    useUiStore.getState().registerSourceSave(fn)
    await expect(useUiStore.getState().sourceSaveFn?.()).resolves.toBe(true)
    useUiStore.getState().registerSourceSave(null)
    expect(useUiStore.getState().sourceSaveFn).toBeNull()
  })
})

describe('uiStore entity-dialog state (A2)', () => {
  it('opens a dialog by mode and closes with null', () => {
    useUiStore.getState().setEntityDialog({ mode: 'subclass', parent: 'http://ex/Dog' })
    expect(useUiStore.getState().entityDialog).toEqual({
      mode: 'subclass',
      parent: 'http://ex/Dog',
    })
    useUiStore.getState().setEntityDialog(null)
    expect(useUiStore.getState().entityDialog).toBeNull()
  })
})

describe('uiStore blank-ontology dialog', () => {
  it('opens and closes the blank-create dialog', () => {
    useUiStore.getState().setBlankOpen(true)
    expect(useUiStore.getState().blankOpen).toBe(true)
    useUiStore.getState().setBlankOpen(false)
    expect(useUiStore.getState().blankOpen).toBe(false)
  })
})

describe('uiStore sidebar collapse', () => {
  it('defaults both sidebars open and collapses them independently', () => {
    expect(useUiStore.getState().leftCollapsed).toBe(false)
    expect(useUiStore.getState().rightCollapsed).toBe(false)
    useUiStore.getState().setLeftCollapsed(true)
    expect(useUiStore.getState().leftCollapsed).toBe(true)
    expect(useUiStore.getState().rightCollapsed).toBe(false)
    useUiStore.getState().setRightCollapsed(true)
    expect(useUiStore.getState().rightCollapsed).toBe(true)
  })
})
