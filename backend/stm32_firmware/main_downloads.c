/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdint.h>
#include <string.h>
#include "r307.h"
#include "uart.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define NUM_ENROLLED_FINGERS   1U
#define ENROLL_PAGE_ID          0U
#define SEARCH_START_PAGE      0U
#define SEARCH_PAGE_COUNT      NUM_ENROLLED_FINGERS

#define MSG_UNLOCKED  "Haptic Pad Unlocked\r\n"
#define MSG_LOCKED    "Haptic Pad Locked\r\n"

/* Host <-> MCU serial command protocol (over debug UART / USART2).
 * A host-side backend (the /api/biometrics/* handlers that app.js calls)
 * writes one command per line and reads back one status token per line.
 *
 *   Host -> MCU : "ENROLL\r\n"
 *   MCU  -> Host: "ENROLL_OK\r\n" | "ENROLL_FAIL\r\n" | "ENROLL_TIMEOUT\r\n"
 *
 *   Host -> MCU : "VERIFY\r\n"
 *   MCU  -> Host: "UNLOCKED\r\n" | "LOCKED\r\n" | "VERIFY_TIMEOUT\r\n" | "VERIFY_ERROR\r\n"
 *
 * Unknown commands get "ERR:UNKNOWN_CMD\r\n".
 */
#define CMD_ENROLL          "ENROLL"
#define CMD_VERIFY          "VERIFY"

#define RESP_ENROLL_OK       "ENROLL_OK\r\n"
#define RESP_ENROLL_FAIL     "ENROLL_FAIL\r\n"
#define RESP_ENROLL_TIMEOUT  "ENROLL_TIMEOUT\r\n"

#define RESP_UNLOCKED        "UNLOCKED\r\n"
#define RESP_LOCKED          "LOCKED\r\n"
#define RESP_VERIFY_TIMEOUT  "VERIFY_TIMEOUT\r\n"
#define RESP_VERIFY_ERROR    "VERIFY_ERROR\r\n"

#define RESP_UNKNOWN_CMD     "ERR:UNKNOWN_CMD\r\n"

#define UART_CMD_BUF_LEN     32U
#define ENROLL_STAGE_TIMEOUT_MS 7000U /* per finger-placement wait */
#define VERIFY_TIMEOUT_MS       2500U
#define PROMPT_GRACE_DELAY_MS    2500U /* pause after each prompt so the
                                         * user has time to react before
                                         * the wait/timeout starts */

#define R307_ERR_TIMEOUT     0xEEU /* local sentinel, not from r307.h */
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart5;
UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_UART5_Init(void);
static void MX_USART2_UART_Init(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* crude blocking delay -- replace with SysTick-based delay_ms() once
 * you have one; placeholder so this compiles standalone */
static void delay_ms(uint32_t ms)
{
    volatile uint32_t count = ms * 4000U; /* rough, uncalibrated */
    while (count--) { }
}

static void debug_print(const char *msg)
{
    debug_uart_transmit((uint8_t *)msg, (uint16_t)strlen(msg));
}

/* Blocks until a finger is detected and imaged, or until timeout_ms
 * elapses. Retries on "no finger present" (confirm_code 0x02); any
 * other non-OK is a hard failure. Returns R307_ERR_TIMEOUT on timeout
 * so callers (and the host over UART) never hang indefinitely. */
static uint8_t wait_for_finger_timeout(uint32_t timeout_ms)
{
    r307_ack_t ack;
    uint8_t status;
    uint32_t start_tick = HAL_GetTick();

    do {
        status = r307_genimg(&ack);
        if (status != R307_OK) {
            return status; /* transport-level failure */
        }
        if (ack.confirm_code == 0x00) {
            return R307_OK; /* image captured */
        }
        if ((HAL_GetTick() - start_tick) >= timeout_ms) {
            return R307_ERR_TIMEOUT;
        }
        delay_ms(100);
    } while (ack.confirm_code == 0x02); /* 0x02 = no finger on sensor */

    return R307_ERR_SENSOR; /* some other sensor-side error */
}

/* Blocks until the finger is lifted (GenImg starts returning "no
 * finger" again), or until timeout_ms elapses -- required between the
 * two scans of an enrollment. Returns R307_OK or R307_ERR_TIMEOUT. */
static uint8_t wait_for_finger_removed_timeout(uint32_t timeout_ms)
{
    r307_ack_t ack;
    uint32_t start_tick = HAL_GetTick();

    ack.confirm_code = 0x00;
    do {
        r307_genimg(&ack);
        if (ack.confirm_code == 0x02) {
            return R307_OK;
        }
        if ((HAL_GetTick() - start_tick) >= timeout_ms) {
            return R307_ERR_TIMEOUT;
        }
        delay_ms(100);
    } while (1);
}

/* Reads one CR/LF-terminated command line from the debug UART (USART2),
 * blocking until a full line arrives. Leading CR/LF bytes are skipped.
 * The buffer is always NUL-terminated. */
static uint16_t uart_read_line(char *buf, uint16_t max_len)
{
    uint16_t idx = 0U;
    uint8_t ch;

    while (idx < (uint16_t)(max_len - 1U)) {
        if (HAL_UART_Receive(&huart2, &ch, 1U, HAL_MAX_DELAY) == HAL_OK) {
            if (ch == '\n' || ch == '\r') {
                if (idx == 0U) {
                    continue; /* ignore stray leading CR/LF */
                }
                break;
            }
            buf[idx++] = (char)ch;
        }
    }
    buf[idx] = '\0';
    return idx;
}

/* Full two-scan enrollment into the given flash library page_id
 * (0..NUM_ENROLLED_FINGERS-1). Returns R307_OK on success,
 * R307_ERR_TIMEOUT if the user never placed/lifted a finger in time,
 * or R307_ERR_SENSOR on any other capture/store failure. */
static uint8_t enroll_finger(uint8_t page_id)
{
    r307_ack_t ack;
    uint8_t status;

    debug_print("Place finger for scan 1\r\n");
    delay_ms(PROMPT_GRACE_DELAY_MS);
    status = wait_for_finger_timeout(ENROLL_STAGE_TIMEOUT_MS);
    if (status != R307_OK) return status;

    status = r307_img2tz(0x01, &ack);
    if (status != R307_OK || ack.confirm_code != 0x00) return R307_ERR_SENSOR;

    debug_print("Lift finger\r\n");
    delay_ms(PROMPT_GRACE_DELAY_MS);
    status = wait_for_finger_removed_timeout(ENROLL_STAGE_TIMEOUT_MS);
    if (status != R307_OK) return status;

    debug_print("Place same finger for scan 2\r\n");
    delay_ms(PROMPT_GRACE_DELAY_MS);
    status = wait_for_finger_timeout(ENROLL_STAGE_TIMEOUT_MS);
    if (status != R307_OK) return status;

    status = r307_img2tz(0x02, &ack);
    if (status != R307_OK || ack.confirm_code != 0x00) return R307_ERR_SENSOR;

    status = r307_regmodel(&ack);
    if (status != R307_OK || ack.confirm_code != 0x00) return R307_ERR_SENSOR;

    status = r307_store(0x01, page_id, &ack);
    if (status != R307_OK || ack.confirm_code != 0x00) return R307_ERR_SENSOR;

    debug_print("Enrolled OK\r\n");
    return R307_OK;
}

/* Handles a host "ENROLL" command: runs the two-scan enrollment into
 * the single reserved slot (overwriting any previous fingerprint
 * there) and writes exactly one status line back to the host. */
static void handle_enroll_command(void)
{
    uint8_t status = enroll_finger(ENROLL_PAGE_ID);

    if (status == R307_OK) {
        debug_print(RESP_ENROLL_OK);
    } else if (status == R307_ERR_TIMEOUT) {
        debug_print(RESP_ENROLL_TIMEOUT);
    } else {
        debug_print(RESP_ENROLL_FAIL);
    }
}

/* Handles a host "VERIFY" command: waits for a finger, matches it
 * against the enrolled template, and writes exactly one status line
 * back to the host (UNLOCKED/LOCKED/VERIFY_TIMEOUT/VERIFY_ERROR). It
 * also prints the human-readable MSG_UNLOCKED/MSG_LOCKED lines for
 * anyone watching the debug console directly. */
static void handle_verify_command(void)
{
    r307_ack_t ack;
    uint8_t status;

    debug_print("Place finger to verify\r\n");
    delay_ms(PROMPT_GRACE_DELAY_MS);
    status = wait_for_finger_timeout(VERIFY_TIMEOUT_MS);
    if (status == R307_ERR_TIMEOUT) {
        debug_print(RESP_VERIFY_TIMEOUT);
        return;
    }
    if (status != R307_OK) {
        debug_print(RESP_VERIFY_ERROR);
        return;
    }

    if (r307_img2tz(0x01, &ack) != R307_OK || ack.confirm_code != 0x00) {
        debug_print(RESP_VERIFY_ERROR);
        return;
    }

    if (r307_search(0x01, SEARCH_START_PAGE, SEARCH_PAGE_COUNT, &ack) != R307_OK) {
        debug_print(RESP_VERIFY_ERROR);
        return;
    }

    if (ack.confirm_code == 0x00) {
        debug_print(MSG_UNLOCKED);
        debug_print(RESP_UNLOCKED);
    } else {
        debug_print(MSG_LOCKED);
        debug_print(RESP_LOCKED);
    }

    /* Don't let a lingering finger immediately retrigger the next
     * command; give the user a bounded window to lift it. */
    wait_for_finger_removed_timeout(VERIFY_TIMEOUT_MS);
}

/* Reads one command line from the host and dispatches it. Unknown or
 * empty lines get a one-line error response so the host never blocks
 * waiting on a reply that will never come. */
static void process_host_command(void)
{
    char cmd[UART_CMD_BUF_LEN];

    uart_read_line(cmd, sizeof(cmd));

    if (strcmp(cmd, CMD_ENROLL) == 0) {
        handle_enroll_command();
    } else if (strcmp(cmd, CMD_VERIFY) == 0) {
        handle_verify_command();
    } else if (cmd[0] != '\0') {
        debug_print(RESP_UNKNOWN_CMD);
    }
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_UART5_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */

  debug_print("Boot OK\r\n");
  debug_print("Waiting for ENROLL/VERIFY commands\r\n");

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    process_host_command();
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 16;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV4;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief UART5 Initialization Function
  * @param None
  * @retval None
  */
static void MX_UART5_Init(void)
{

  /* USER CODE BEGIN UART5_Init 0 */

  /* USER CODE END UART5_Init 0 */

  /* USER CODE BEGIN UART5_Init 1 */

  /* USER CODE END UART5_Init 1 */
  huart5.Instance = UART5;
  huart5.Init.BaudRate = 57600;
  huart5.Init.WordLength = UART_WORDLENGTH_8B;
  huart5.Init.StopBits = UART_STOPBITS_1;
  huart5.Init.Parity = UART_PARITY_NONE;
  huart5.Init.Mode = UART_MODE_TX_RX;
  huart5.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart5.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart5) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN UART5_Init 2 */

  /* USER CODE END UART5_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(LD2_GPIO_Port, LD2_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin : B1_Pin */
  GPIO_InitStruct.Pin = B1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(B1_GPIO_Port, &GPIO_InitStruct);

  /*Configure GPIO pin : LD2_Pin */
  GPIO_InitStruct.Pin = LD2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LD2_GPIO_Port, &GPIO_InitStruct);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */