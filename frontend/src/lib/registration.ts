type ChoiceOption = {
  value: string
  label: string
}

export function hasReusableOAuthBrowser(config: { chrome_user_data_dir?: string; chrome_cdp_url?: string }) {
  return Boolean(config.chrome_user_data_dir?.trim() || config.chrome_cdp_url?.trim())
}

function getOptionLabel(value: string, options: ChoiceOption[] = []) {
  return options.find(item => item.value === value)?.label || value
}

export function pickOAuthExecutor(
  supportedExecutors: string[],
  preferredExecutor: string,
  reusableBrowser: boolean,
) {
  if (supportedExecutors.includes(preferredExecutor) && preferredExecutor !== 'protocol') {
    return preferredExecutor
  }
  if (reusableBrowser && supportedExecutors.includes('headless')) {
    return 'headless'
  }
  if (supportedExecutors.includes('headed')) {
    return 'headed'
  }
  if (supportedExecutors.includes('headless')) {
    return 'headless'
  }
  return supportedExecutors[0] || ''
}

export function buildRegistrationOptions(platformMeta: any) {
  const supportedModes: string[] = platformMeta?.supported_identity_modes || []
  const supportedOAuth: string[] = platformMeta?.supported_oauth_providers || []
  const identityModeOptions: ChoiceOption[] = platformMeta?.supported_identity_mode_options || []
  const oauthProviderOptions: ChoiceOption[] = platformMeta?.supported_oauth_provider_options || []
  const options: Array<{
    key: string
    label: string
    description: string
    identityProvider: string
    oauthProvider: string
  }> = []

  if (supportedModes.includes('mailbox')) {
    options.push({
      key: 'mailbox',
      label: getOptionLabel('mailbox', identityModeOptions),
      description: `Use ${getOptionLabel('mailbox', identityModeOptions)} to auto-receive verification codes and complete registration`,
      identityProvider: 'mailbox',
      oauthProvider: '',
    })
  }

  if (supportedModes.includes('oauth_browser')) {
    supportedOAuth.forEach((provider: string) => {
      const providerLabel = getOptionLabel(provider, oauthProviderOptions)
      options.push({
        key: `oauth:${provider}`,
        label: providerLabel,
        description: `Automatically create platform account using ${providerLabel}`,
        identityProvider: 'oauth_browser',
        oauthProvider: provider,
      })
    })
  }

  return options
}

export function buildExecutorOptions(
  identityProvider: string,
  supportedExecutors: string[],
  reusableBrowser: boolean,
  executorOptions: ChoiceOption[] = [],
) {
  return supportedExecutors.map((executor) => {
    const option = {
      value: executor,
      label: getOptionLabel(executor, executorOptions),
      description: '',
      disabled: false,
      reason: '',
    }

    if (executor === 'protocol') {
      option.description = 'Automatically register via protocol without opening a browser'
      if (identityProvider !== 'mailbox') {
        option.disabled = true
        option.reason = 'Third-party account registration must be completed via browser automation'
      }
      return option
    }

    if (executor === 'headless') {
      option.description = identityProvider === 'mailbox'
        ? 'Browser runs in the background automatically, no UI visible'
        : 'Reuse local browser login state to complete third-party login in background'
      if (identityProvider === 'oauth_browser' && !reusableBrowser) {
        option.disabled = true
        option.reason = 'Chrome Profile path or Chrome CDP address must be configured in global settings first'
      }
      return option
    }

    option.description = 'Opens a browser window, but the system still runs automatically without additional interaction'
    return option
  })
}
